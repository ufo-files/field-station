"""Google device authorization and bounded, resumable YouTube uploads."""
import json
import os
import tempfile
import fcntl
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler
from experiments import load,save


class YouTubeError(OSError):
    def __init__(self,status,reason,message):
        super().__init__(message);self.status=status;self.reason=reason


def private_save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.parent.chmod(0o700)
    name=None
    try:
        with tempfile.NamedTemporaryFile('w',dir=path.parent,prefix='.'+path.name+'-',delete=False) as stream:
            name=stream.name;os.fchmod(stream.fileno(),0o600)
            json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if name and os.path.exists(name):os.unlink(name)


def upload_url(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in ('www.googleapis.com','youtube.googleapis.com') or parsed.path!='/upload/youtube/v3/videos':
        raise ValueError('Unexpected resumable upload server')
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class YouTubeAPI:
    def __init__(self,private):
        self.private=Path(private)
        self.opener=build_opener(NoRedirect())
        self.auth_error=None
        token=load(self.private/'token.json',{})
        if token.get('refresh_token_expires_in') and not token.get('refresh_expires_at'):
            authorized=token.get('expires_at',time.time())-token.get('expires_in',3600)
            token.update(authorized_at=authorized,refresh_expires_at=authorized+token['refresh_token_expires_in'])
            private_save(self.private/'token.json',token)

    def raw(self,method,url,body=None,headers=None,auth=False):
        headers=dict(headers or {})
        if auth:headers['Authorization']='Bearer '+self.token()
        try:
            with self.opener.open(Request(url,data=body,headers=headers,method=method),timeout=45) as r:
                raw=r.read();return r.status,dict(r.headers),json.loads(raw) if raw else {}
        except HTTPError as e:
            raw=e.read()
            try:data=json.loads(raw) if raw else {}
            except ValueError:data={}
            if e.code==308:return 308,dict(e.headers),data
            value=data.get('error',{})
            if isinstance(value,str):reason=value;message=data.get('error_description',value)
            else:
                reason=next(iter(value.get('errors',[{}])),{}).get('reason','http_error')
                message=value.get('message',f'YouTube request failed ({e.code})')
            raise YouTubeError(e.code,reason,message)

    def form(self,url,data):
        return self.raw('POST',url,urlencode(data).encode(),{'Content-Type':'application/x-www-form-urlencoded'})[2]

    def configured(self):
        return bool(load(self.private/'client.json',{}).get('client_id'))

    def connected(self):
        token=load(self.private/'token.json',{})
        if token.get('refresh_expires_at') and token['refresh_expires_at']<=time.time():self.auth_error='Google authorization expired; connect again.'
        return bool(token.get('refresh_token')) and not self.auth_error

    def set_client(self,body):
        value=body.get('installed') or body.get('web') or body
        client_id=str(value.get('client_id','')).strip();secret=str(value.get('client_secret','')).strip()
        if not client_id.endswith('.apps.googleusercontent.com') or not secret or len(secret)>4096:
            raise ValueError('A Google OAuth client ID and client secret are required, not an account password.')
        old=load(self.private/'client.json',{})
        if old.get('client_id')!=client_id:
            (self.private/'token.json').unlink(missing_ok=True)
            (self.private/'device.json').unlink(missing_ok=True)
        self.auth_error=None
        private_save(self.private/'client.json',dict(client_id=client_id,client_secret=secret))

    def start_auth(self):
        client=load(self.private/'client.json',{})
        if not client:raise ValueError('Configure a Google OAuth client for TVs and Limited Input devices first.')
        result=self.form('https://oauth2.googleapis.com/device/code',dict(client_id=client['client_id'],scope='https://www.googleapis.com/auth/youtube'))
        result.update(expires_at=time.time()+result['expires_in'],next_poll=time.time()+result.get('interval',5))
        private_save(self.private/'device.json',result)
        return self.auth_status()

    def auth_status(self):
        device=load(self.private/'device.json',{})
        token=load(self.private/'token.json',{})
        return dict(configured=self.configured(),connected=self.connected(),error=self.auth_error,
            user_code=device.get('user_code'),verification_url=device.get('verification_url'),expires_at=device.get('expires_at'),refresh_expires_at=token.get('refresh_expires_at'))

    def poll_auth(self):
        self.private.mkdir(parents=True,exist_ok=True,mode=0o700)
        with (self.private/'oauth.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return False
            return self._poll_auth()

    def _poll_auth(self):
        device=load(self.private/'device.json',{})
        if not device or time.time()<device.get('next_poll',0):return False
        if time.time()>device['expires_at']:
            (self.private/'device.json').unlink(missing_ok=True);self.auth_error='Authorization code expired; connect again.';return False
        client=load(self.private/'client.json',{})
        try:
            result=self.form('https://oauth2.googleapis.com/token',dict(client_id=client['client_id'],client_secret=client['client_secret'],
                device_code=device['device_code'],grant_type='urn:ietf:params:oauth:grant-type:device_code'))
        except YouTubeError as error:
            if error.reason in ('authorization_pending','slow_down'):
                interval=device.get('interval',5)+(5 if error.reason=='slow_down' else 0)
                device.update(interval=interval,next_poll=time.time()+interval);private_save(self.private/'device.json',device);return False
            (self.private/'device.json').unlink(missing_ok=True);self.auth_error=str(error);return False
        previous=load(self.private/'token.json',{})
        old_refresh=previous.get('refresh_token')
        previous.update(result,expires_at=time.time()+result.get('expires_in',3600),authorized_at=time.time())
        if result.get('refresh_token_expires_in'):previous['refresh_expires_at']=time.time()+result['refresh_token_expires_in']
        elif result.get('refresh_token') and result['refresh_token']!=old_refresh:
            previous.pop('refresh_expires_at',None);previous.pop('refresh_token_expires_in',None)
        private_save(self.private/'token.json',previous)
        (self.private/'device.json').unlink(missing_ok=True);self.auth_error=None;return True

    def token(self):
        token=load(self.private/'token.json',{})
        if token.get('access_token') and token.get('expires_at',0)>time.time()+60:return token['access_token']
        client=load(self.private/'client.json',{})
        if not token.get('refresh_token'):raise ValueError('Connect the YouTube channel first.')
        try:
            result=self.form('https://oauth2.googleapis.com/token',dict(client_id=client['client_id'],client_secret=client['client_secret'],
                refresh_token=token['refresh_token'],grant_type='refresh_token'))
        except YouTubeError as error:
            if error.reason=='invalid_grant':self.auth_error='Google authorization expired or was revoked. Connect again.'
            raise
        token.update(result,expires_at=time.time()+result.get('expires_in',3600))
        private_save(self.private/'token.json',token);return token['access_token']

    def list(self,resource,**params):
        return self.raw('GET','https://www.googleapis.com/youtube/v3/'+resource+'?'+urlencode(params),auth=True)[2]

    def channel(self,expected):
        result=self.list('channels',part='id,snippet',mine='true')
        items=result.get('items',[])
        match=next((i for i in items if i['id']==expected),None)
        if not match:raise ValueError('The authorized channel is not @ufofilesproject. Connect using that channel.')
        return dict(id=match['id'],title=match['snippet']['title'])

    def initiate(self,metadata,size):
        url='https://www.googleapis.com/upload/youtube/v3/videos?'+urlencode(dict(uploadType='resumable',part='snippet,status',notifySubscribers='false'))
        status,headers,body=self.raw('POST',url,json.dumps(metadata).encode(),
            {'Content-Type':'application/json; charset=UTF-8','X-Upload-Content-Type':'video/mp4','X-Upload-Content-Length':str(size)},auth=True)
        location=next((v for k,v in headers.items() if k.lower()=='location'),None)
        if not location:raise OSError('YouTube did not return a resumable upload location')
        return upload_url(location)

    def progress(self,url,size):
        return self.raw('PUT',upload_url(url),b'',{'Content-Length':'0','Content-Range':f'bytes */{size}'},auth=True)

    def chunk(self,url,offset,size,data):
        return self.raw('PUT',upload_url(url),data,{'Content-Type':'video/mp4','Content-Length':str(len(data)),
            'Content-Range':f'bytes {offset}-{offset+len(data)-1}/{size}'},auth=True)

    @staticmethod
    def offset(headers):
        value=next((v for k,v in headers.items() if k.lower()=='range'),'')
        match=re.fullmatch(r'bytes=0-([0-9]+)',value)
        return int(match[1])+1 if match else 0

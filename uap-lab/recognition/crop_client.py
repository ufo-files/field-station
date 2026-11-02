"""Bounded synchronous request protocol for one persistent Core ML model process."""
import base64,json,queue,subprocess,threading,time,uuid
MAX_REQUEST_BYTES=32*1024*1024
class CropWorkerError(RuntimeError):pass
class CropClassifier:
    def __init__(self,binary,model,version,timeout=30):
        self.version=version;self.timeout=timeout;self.lock=threading.Lock();self.responses=queue.Queue();self.errors=[]
        self.proc=subprocess.Popen([str(binary),str(model),version],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        def read():
            try:
                for line in self.proc.stdout:
                    self.responses.put(json.loads(line))
            except Exception as exc:self.responses.put(CropWorkerError(str(exc)))
            finally:self.responses.put(CropWorkerError('Classifier exited before a response'))
        def stderr():
            for line in self.proc.stderr:self.errors[:]=[*self.errors[-9:],line.strip()]
        self.threads=[threading.Thread(target=read,daemon=True),threading.Thread(target=stderr,daemon=True)]
        for thread in self.threads:thread.start()
        try:
            ready=self.receive()
            if not ready.get('ready') or ready.get('version')!=version:raise CropWorkerError('Model startup/version mismatch')
            self.startup=ready
        except BaseException:self.close();raise
    def receive(self):
        try:value=self.responses.get(timeout=self.timeout)
        except queue.Empty:raise CropWorkerError('Classifier response timed out')
        if isinstance(value,Exception):raise value
        return value
    def predict(self,images,request_id=None):
        results=[];request_id=request_id or uuid.uuid4().hex
        with self.lock:
            offset=0
            while offset<len(images):
                rid=f'{request_id}:{offset}';batch=[]
                size=len(json.dumps(dict(id=rid,images=[])).encode('utf-8'))
                for image in images[offset:offset+256]:
                    encoded_image=base64.b64encode(image).decode()
                    added=len(encoded_image)+2+(2 if batch else 0)
                    if size+added>MAX_REQUEST_BYTES:
                        if not batch:raise CropWorkerError('Single crop exceeds protocol size')
                        break
                    batch.append(encoded_image);size+=added
                encoded=json.dumps(dict(id=rid,images=batch))
                try:self.proc.stdin.write(encoded+'\n');self.proc.stdin.flush()
                except (BrokenPipeError,OSError):raise CropWorkerError('Classifier input pipe failed')
                reply=self.receive()
                if reply.get('error'):raise CropWorkerError(reply['error'])
                if reply.get('id')!=rid or reply.get('version')!=self.version:raise CropWorkerError('Classifier response does not match input frame/model')
                values=reply.get('results',[])
                if len(values)!=len(batch) or [r.get('index') for r in values]!=list(range(len(batch))):raise CropWorkerError('Missing, reordered or duplicate crop results')
                results.extend(dict(row,index=offset+row['index']) for row in values)
                offset+=len(batch)
        return results
    def close(self):
        try:self.proc.stdin.close()
        except (AttributeError,OSError):pass
        try:self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:self.proc.terminate();self.proc.wait(timeout=5)
        for thread in self.threads:thread.join(timeout=1)
        self.proc.stdout.close();self.proc.stderr.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

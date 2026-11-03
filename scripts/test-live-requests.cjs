const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../uap-lab/static/app.js'),'utf8');
const code=source.slice(source.indexOf('let liveObjectURL='),source.indexOf("$('liveImage').onload=",source.indexOf('let liveObjectURL=')));
let now=100,behavior='ok',timer,serial=0;const image={src:'old'},revoked=[];
const box={AbortController,Image:class{decode(){return Promise.resolve()}},performance:{now:()=>now},setTimeout:f=>(timer=f,1),clearTimeout(){},URL:{createObjectURL:()=>`blob:${++serial}`,revokeObjectURL:u=>revoked.push(u)},$:()=>image,paintLiveTags(){},updateLiveHealth(){},fetch:async(url,options)=>{
 if(behavior==='hang')return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(Error('aborted'))));
 return {ok:behavior==='ok',blob:async()=>({})};
}};vm.createContext(box);vm.runInContext('let liveImageLoading=false,lastRenderedFrameEpoch=null,liveFrameReceivedAt=null;'+code,box);
(async()=>{
 const apiSource=source.split('\n').find(line=>line.startsWith('async function api('));
 const apiContext={AbortController,setTimeout,clearTimeout,window:{FIELD_PUBLIC_READ_ONLY:true},token:'test',fetch:async(_url,options)=>new Promise((_,reject)=>options.signal.addEventListener('abort',()=>{const error=new Error('aborted');error.name='AbortError';reject(error)}))};
 vm.createContext(apiContext);vm.runInContext(apiSource,apiContext);
 await assert.rejects(vm.runInContext("api('/api/state',undefined,1)",apiContext),/Connection to the station timed out\. Please try again\./);
 await assert.rejects(vm.runInContext("api('/api/review',{},1)",apiContext),/Connection to the station timed out/);
 apiContext.window.FIELD_PUBLIC_READ_ONLY=false;
 await assert.rejects(vm.runInContext("api('/api/state',undefined,1)",apiContext),/Connection to the station timed out/);
 await assert.rejects(vm.runInContext("api('/api/review',{},1)",apiContext),/Your selections are kept/);
 await vm.runInContext('loadLiveFrame(1)',box);assert.equal(image.src,'blob:1');assert.equal(vm.runInContext('liveFrameReceivedAt',box),100);
 behavior='hang';now=200;const pending=vm.runInContext('loadLiveFrame(2)',box);timer();await pending;
 assert.equal(vm.runInContext('liveImageLoading',box),false);assert.equal(image.src,'blob:1');assert.equal(vm.runInContext('liveFrameReceivedAt',box),100);
 behavior='ok';now=300;await vm.runInContext('loadLiveFrame(2)',box);assert.equal(image.src,'blob:2');assert.equal(vm.runInContext('liveFrameReceivedAt',box),300);assert(revoked.includes('blob:1'));
 now=400;await vm.runInContext('loadLiveFrame(2)',box);assert.equal(vm.runInContext('liveFrameReceivedAt',box),300,'repeated frame must not reset freshness');
 behavior='error';await vm.runInContext('loadLiveFrame(3)',box);assert.equal(vm.runInContext('liveImageLoading',box),false);assert.equal(vm.runInContext('liveFrameReceivedAt',box),300);
 console.log('Passed: timeout recovery, retained image, advancing frames, repeated/stale frames, failed request');
})().catch(e=>{console.error(e);process.exit(1)});

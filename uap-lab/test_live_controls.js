const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync(__dirname+'/static/index.html','utf8');
const source=fs.readFileSync(__dirname+'/static/app.js','utf8');
const ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);
assert.equal(ids.length,new Set(ids).size);
assert(!html.includes('class="mark"'));
assert(!html.match(/id="sessionToggle"[^>]*\bchecked\b/));
const noop=()=>{};
function element(){return {hidden:false,value:'',checked:false,disabled:false,style:{},dataset:{},width:600,height:140,naturalWidth:1920,naturalHeight:1080,
 classList:{toggle:noop,add:noop,remove:noop},getContext:()=>({clearRect:noop,drawImage:noop,fillText:noop,fillRect:noop,strokeRect:noop,beginPath:noop,moveTo:noop,lineTo:noop,stroke:noop,setLineDash:noop,measureText:()=>({width:10})}),
 getBoundingClientRect:()=>({width:1280,height:800}),replaceChildren:noop,append:noop,setAttribute:noop,addEventListener:noop,focus:noop,pause:noop,closest:()=>null};}
const nodes=Object.fromEntries(ids.map(id=>[id,element()]));nodes.canvas.parentElement=element();nodes.labelSource.value='all';nodes.mainNav.hidden=true;nodes.infoPanel.hidden=true;
let active=null,failStart=false;const posts=[];
const fixture={token:'test',free_bytes:100000,labels:['anomalous','bird'],videos:[],runs:[],model:null,publication:{enabled:true,phase:'published',url:'https://github.com/example/model'}};
const context={console,AbortController,Date,Math,Number,Map,Set,Uint8Array,Promise,
 document:{getElementById:id=>{assert(nodes[id],id);return nodes[id]},createElement:element,createTextNode:v=>v,createDocumentFragment:element,addEventListener:noop,body:element(),activeElement:null},
 window:{addEventListener:noop},localStorage:{getItem:()=>null,setItem:noop,removeItem:noop},
 ResizeObserver:class{observe(){}},setTimeout:()=>1,clearTimeout:noop,setInterval:noop,
 fetch:async(path,options={})=>{let data;
  if(options.method==='POST'){posts.push({path,body:JSON.parse(options.body)});if(path.endsWith('/start')){if(failStart)return {ok:false,json:async()=>({error:'Capture unavailable'})};active={id:'session-1',rf_records:2}}else if(path.endsWith('/stop'))active=null;data={};}
  else if(path==='/api/state')data=fixture;
  else if(path==='/api/live/session')data={active,recent_manual:[]};
  else if(path==='/api/live/status')data={objects:[],events:[]};
  else if(path==='/api/live/rf')data={receivers:{}};
  else throw Error('Unexpected request '+path);
  return {ok:true,json:async()=>data};}};
vm.createContext(context);vm.runInContext(source,context);
async function settle(){for(let i=0;i<30;i++)await Promise.resolve()}
(async()=>{await settle();assert.equal(posts.length,0,'Page load must not start a session');assert.equal(nodes.sessionToggle.checked,false);
 nodes.sessionToggle.checked=true;nodes.sessionToggle.onchange();await settle();assert.equal(posts.at(-1).path,'/api/live/start');assert.equal(nodes.sessionToggle.checked,true);
 nodes.sessionToggle.checked=false;nodes.sessionToggle.onchange();await settle();assert.equal(posts.at(-1).path,'/api/live/stop');assert.equal(posts.at(-1).body.session_id,'session-1');assert.equal(nodes.sessionToggle.checked,false);
 failStart=true;nodes.sessionToggle.checked=true;nodes.sessionToggle.onchange();await settle();assert.equal(nodes.sessionToggle.checked,false);
 nodes.menuToggle.onclick();assert.equal(nodes.mainNav.hidden,false);nodes.infoToggle.onclick();assert.equal(nodes.mainNav.hidden,true);assert.equal(nodes.infoPanel.hidden,false);
 assert.equal(nodes.rfStatus.textContent,'Waiting for receivers');
 assert.equal(nodes.sessionStatus.textContent,'');
 const drawn=[];const canvasContext=nodes.liveBoxes.getContext();canvasContext.strokeRect=(...box)=>drawn.push(box);nodes.liveBoxes.getContext=()=>canvasContext;
 vm.runInContext("liveState={inference_epoch:Date.now()/1000,motion_epoch:Date.now()/1000,width:1920,height:1080,motion_objects:[{box:[1,2,3,4],label:'motion'}],objects:[{box:[10,20,30,40],label:'cloud'},{box:[50,60,70,80],label:'bird'}]};paintLiveTags()",context);
 assert.equal(drawn.length,1,'Only the trained non-cloud match should be drawn');assert.equal(drawn[0][0],50);
 for(const [hour,color] of [[6,'#f3f7fa'],[7,'#111b22'],[18,'#111b22'],[19,'#f3f7fa']]){
 vm.runInContext(`rfLocalHour=${hour};paintRF('rfNarrow',null)`,context);
 for(const id of ['rfOverlay','menuToggle','infoToggle','sessionLabel','sessionStatus'])assert.equal(nodes[id].style.color,color,id+' hour '+hour);
 }
 for(const [width,height] of [[1280,800],[390,844],[1920,1080],[2000,800]]){
 nodes.liveViewer.getBoundingClientRect=()=>({width,height});vm.runInContext('fitLiveStage()',context);
 const stageWidth=parseFloat(nodes.liveStage.style.width),stageHeight=parseFloat(nodes.liveStage.style.height);
 assert(stageWidth>=width&&stageHeight>=height,'Video must cover viewport');assert(Math.abs(stageWidth/stageHeight-16/9)<.00001,'Preserve aspect ratio');
 }
 const beforeSuggestionPosts=posts.length;
 vm.runInContext("current={id:'fixture',annotations:[]};state.labels=['bird','airplane'];drafts=[];frozen={native:true,time:.1,image:{}};activeSuggestion={id:'one',track_id:'bird-track',time:.1,bounds:{x:.1,y:.1,w:.1,h:.1}}",context);
 nodes.suggestionLabel.value='';nodes.useSuggestion.onclick();assert.equal(vm.runInContext('drafts.length',context),0,'Unknown label cannot be accepted');
 nodes.suggestionLabel.value='bird';nodes.useSuggestion.onclick();assert.equal(vm.runInContext('drafts.length',context),1);
 vm.runInContext("activeSuggestion={id:'two',track_id:'plane-track',time:.1,bounds:{x:.5,y:.5,w:.1,h:.1}}",context);nodes.suggestionLabel.value='airplane';nodes.useSuggestion.onclick();
 vm.runInContext("frozen.time=.2;activeSuggestion={id:'three',track_id:'bird-track',time:.2,bounds:{x:.2,y:.1,w:.1,h:.1}}",context);nodes.suggestionLabel.value='bird';nodes.useSuggestion.onclick();
 assert.equal(vm.runInContext('drafts.length',context),3);assert.equal(vm.runInContext('new Set(drafts.map(d=>d.track_id)).size',context),2);assert.equal(vm.runInContext('drafts[1].label',context),'airplane');assert.equal(posts.length,beforeSuggestionPosts,'Suggestions stay drafts until explicit review save');
 console.log('PASS: no auto-start; server-synchronized session switch; guarded Stop; failure rollback; panels; missing RF');
})().catch(e=>{console.error(e);process.exitCode=1});

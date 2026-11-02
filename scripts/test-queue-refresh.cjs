const fs=require('fs'),vm=require('vm'),assert=require('assert');
const s=fs.readFileSync(require('path').join(__dirname,'../uap-lab/static/label-videos.js'),'utf8');
const fn=s.slice(s.indexOf(' async function queuePage('),s.indexOf(' async function load(){'));
let pages=[],calls=[];
const box={source:'all',encodeURIComponent,api:async url=>{calls.push(url);if(!pages.length)throw Error('Unexpected request');return pages.shift()}};vm.createContext(box);vm.runInContext(fn,box);
(async()=>{
 pages=[{items:[],next_cursor:'d:a'},{items:[{id:'frame'}],next_cursor:'v:'},{items:[],next_cursor:'v:b'},{items:[{id:'video'}],next_cursor:null}];
 let p=await box.queuePage();assert.equal(p.items.length,2);assert.equal(p.total,2);assert.equal(p.next_cursor,null);assert.equal(calls.length,4);
 pages=[{items:[],next_cursor:'d:a'},{items:[{id:'frame'}],next_cursor:'v:'},{items:[],next_cursor:'v:b'},{items:[{id:'video'}],next_cursor:null}];
 const again=await box.queuePage();assert.equal(JSON.stringify(again),JSON.stringify(p),'refresh retains the same sparse page');
 pages=[{items:[],next_cursor:'d:a'},{items:[],next_cursor:null}];p=await box.queuePage();assert.equal(p.items.length,0);assert.equal(p.next_cursor,null);
 pages=[{items:Array.from({length:100},(_,id)=>({id})),next_cursor:'d:next'}];p=await box.queuePage();assert.equal(p.items.length,100);assert.equal(p.next_cursor,'d:next');
 console.log('Passed: sparse pages, stable refresh, empty queue, full-page pagination');
})().catch(e=>{console.error(e);process.exit(1)});

// Exercise actual queue functions with deferred responses: saving must win over
// old loads, and reviews from another tab must disappear beyond the first page.
(async()=>{
 let resolve,scheduled=[],statusCalls=0;
 const elements={moreDetections:{},detectionQueue:{children:[],append(el){this.children.push(el)}},queueStatus:{},queueEmpty:{}};
 const context={document:{hidden:false},window:{scrollY:500},token:'csrf',loading:false,more:true,total:110,cursor:'page2',labels:[],reviewRevision:0,reconciling:false,source:'all',shown:new Set(),pending:new Map(),Set,Map,
  $:id=>elements[id],setTimeout:fn=>scheduled.push(fn),updateStatus(){},card:r=>({dataset:r}),queuePage:()=>new Promise(r=>resolve=r),api:async(path,body)=>{statusCalls++;assert.equal(path,'/api/label-queue/status');assert(body.items.some(i=>i.id==='105'));return {reviewed:[{id:'105',kind:'detection'},{id:'106',kind:'detection'}]}}};
 vm.createContext(context);
 vm.runInContext(s.slice(s.indexOf(' async function load(){'),s.indexOf(' async function refreshTop(){')),context);
 vm.runInContext(s.slice(s.indexOf(' async function reconcileReviewed(){'),s.indexOf(' setInterval(reconcileReviewed')),context);
 const loading=context.load();context.reviewRevision++;resolve({items:[{id:'saved'}],next_cursor:null,labels:[],total:1});await loading;
 assert.equal(elements.detectionQueue.children.length,0,'late queue response cannot resurrect a saved card');assert.equal(scheduled.length,1);
 elements.detectionQueue.children=Array.from({length:110},(_,i)=>({dataset:{id:String(i),kind:'detection'},remove(){elements.detectionQueue.children=elements.detectionQueue.children.filter(e=>e!==this)}}));
 context.shown=new Set(elements.detectionQueue.children.map(e=>e.dataset.id));context.pending.set('106',{body:{request_id:'pending',label:'cloud'}});
 await context.reconcileReviewed();assert.equal(statusCalls,1);assert(!context.shown.has('105'),'older reviewed card removed while scrolled');assert(context.shown.has('106'),'pending save retained');assert.equal(context.shown.size,109);
 context.api=()=>new Promise(r=>resolve=r);const reconciliation=context.reconcileReviewed();context.reviewRevision++;resolve({reviewed:[{id:'104'}]});await reconciliation;assert(context.shown.has('104'),'review response predating undo ignored');
 console.log('Passed: late-load save race, older-card reconciliation while scrolled, pending-save preservation, undo race');
})().catch(e=>{console.error(e);process.exit(1)});

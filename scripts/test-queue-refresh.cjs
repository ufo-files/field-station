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

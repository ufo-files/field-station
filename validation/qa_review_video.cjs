// Read-only playback QA against a saved review; does not submit annotations.
const {chromium,webkit,devices}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('assert');
const url=process.env.FIELD_REVIEW_URL;
if(!url)throw Error('Set FIELD_REVIEW_URL to an existing email review URL');
(async()=>{
 for(const type of [chromium,webkit]){
  const browser=await type.launch();
  try{
   const page=await browser.newPage(type===webkit?{...devices['iPhone 13']}:{viewport:{width:1280,height:900}});
   const errors=[];let blocked=true;page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/api/email-review/video?*',r=>blocked?r.abort():r.continue());
   await page.goto(url);
   await page.waitForFunction(()=>document.querySelector('#label').options.length>0);
   const info=await (await page.request.get(new URL('/api/email-review'+new URL(url).search,url).href)).json();
   assert(!info.completed,'Use an open review for playback QA');
   assert(await page.locator('#load-video').isEnabled());blocked=false;await page.click('#load-video');
   await page.waitForFunction(()=>!document.querySelector('#scrub').disabled&&!document.querySelector('#video').seeking);
   const first=await page.locator('#video').evaluate(v=>({time:v.currentTime,width:v.videoWidth,height:v.videoHeight,duration:v.duration}));
   assert(first.width>0&&first.height>0);assert(Math.abs(first.time-info.clip.event_time)<.04);
   await page.click('#play');await page.waitForTimeout(600);await page.click('#play');
   assert(await page.locator('#video').evaluate(v=>v.currentTime)>first.time);
   const seek=Math.max(0,first.duration*.7);
   await page.locator('#scrub').evaluate((e,t)=>{e.value=String(t);e.dispatchEvent(new Event('input'))},seek);
   await page.waitForFunction(()=>!document.querySelector('#video').seeking);
   assert(Math.abs(await page.locator('#video').evaluate(v=>v.currentTime)-seek)<.05);
   assert.deepEqual(errors,[]);
   console.log(type.name(),'PASS: blocked preload, tap-to-load, alert-frame seek, play/pause, scrub; no JavaScript errors');
  }finally{await browser.close()}
 }
})().catch(e=>{console.error(e);process.exit(1)});

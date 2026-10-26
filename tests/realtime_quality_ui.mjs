// Check visible contrast on soft detail at the actual display size, not only that pixels changed.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const url=process.env.TEST_URL||'http://127.0.0.1:8082',output=process.env.TEST_OUTPUT||'/data/workspace/tg-web-archive-e2e';
await fs.mkdir(output,{recursive:true});
const baseline=process.env.BASELINE_RENDERER_PATH?await fs.readFile(process.env.BASELINE_RENDERER_PATH,'utf8'):null;
const photo=process.env.QUALITY_IMAGE_PATH?'data:image/png;base64,'+(await fs.readFile(process.env.QUALITY_IMAGE_PATH)).toString('base64'):null;
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader','--autoplay-policy=no-user-gesture-required']});
const errors=[],results=[];
async function render(width,old=false){
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.setContent(`<style>body{margin:0;background:#111;color:white}#shell{width:${width}px}#stage{position:relative;width:${width}px;height:${width*720/1280}px;background:black}.player-stage video{position:absolute;width:100%;height:100%;object-fit:contain}.tools{display:none}</style><div id="shell"><div class="player-stage" id="stage"><video muted playsinline autoplay></video></div><div class="tools"><button id="realtimeButton"></button><button id="realtimeOpen"></button><p id="realtimeStatus"></p><section id="realtimePanel" hidden><p id="realtimeDetail"></p><button id="realtimeClose"></button><button id="realtimeCompare"></button>${['off','natural','clear','strong'].map(m=>`<button data-realtime-mode="${m}"></button>`).join('')}<input id="realtimeStrength" type="range" min="0" max="100"><output id="realtimeStrengthValue"></output><button id="realtimeSplit"></button><label id="realtimeSplitControls" hidden><input id="realtimeSplitPosition" type="range" min="10" max="90" value="50"></label><button id="realtimeSplitQuick"></button></section></div></div>`);
  await page.addStyleTag({url:url+'/realtime-enhancement.css'});
  if(old)await page.addScriptTag({content:baseline});else await page.addScriptTag({url:url+'/realtime-enhancement.js'});
  await page.evaluate(async photo=>{
    localStorage.removeItem('tvm-realtime-enhancement-v1');
    const canvas=document.createElement('canvas');canvas.width=1280;canvas.height=720;
    const x=canvas.getContext('2d');x.fillStyle='#888';x.fillRect(0,0,1280,720);
    const gradient=x.createLinearGradient(0,0,1280,720);gradient.addColorStop(0,'#596b71');gradient.addColorStop(1,'#b0a895');x.fillStyle=gradient;x.fillRect(0,0,1280,720);
    x.filter='blur(1px)';
    for(let row=0;row<6;row++){
      const pitch=3+row*2;x.fillStyle='#808080';x.fillRect(25,row*100+15,580,80);
      x.fillStyle='#a1a1a1';for(let i=0;i<560;i+=pitch*2)x.fillRect(35+i,row*100+20,pitch,70);
    }
    x.fillStyle='#dedbd3';x.font='30px sans-serif';x.fillText('Soft detail 1080p / 720p',40,680);
    if(photo){const image=new Image();image.src=photo;await image.decode();x.drawImage(image,620,20,640,640);}
    else {x.strokeStyle='#adb1ae';x.lineWidth=2;for(let i=0;i<100;i++){x.beginPath();x.moveTo(640+i*5,30);x.lineTo(650+i*5,650);x.stroke();}x.font='38px serif';x.fillStyle='#555d62';x.fillText('Fine texture',680,680);}
    x.filter='none';
    const v=document.querySelector('video');v.srcObject=canvas.captureStream(1);await v.play();
    await new Promise(resolve=>{if(v.readyState>=2)resolve();else v.addEventListener('loadeddata',resolve,{once:true})});v.pause();
    window.sourceCanvas=canvas;window.renderer=attachRealtimeEnhancement({shell:document.querySelector('#shell'),stage:document.querySelector('#stage'),video:v});
  },photo);
  const result=await page.evaluate(()=>{
    renderer.setMode('clear');const c=document.querySelector('#realtimeCanvas'),v=document.querySelector('video'),gl=c.getContext('webgl'),w=c.width,h=c.height;
    function read(){const p=new Uint8Array(w*h*4),top=new Uint8ClampedArray(w*h*4);gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,p);for(let y=0;y<h;y++)top.set(p.subarray((h-y-1)*w*4,(h-y)*w*4),y*w*4);return top;}
    const enhanced=read(),base=document.createElement('canvas');base.width=w;base.height=h;const ctx=base.getContext('2d');ctx.drawImage(v,0,0,w,h);const original=ctx.getImageData(0,0,w,h).data;
    function metric(a,b){let mean=0,changed=0;for(let i=0;i<a.length;i+=4)for(let k=0;k<3;k++){const d=Math.abs(a[i+k]-b[i+k]);mean+=d;if(d>=3)changed++;}return {mean:mean/(w*h*3),visibleFraction:changed/(w*h*3)};}
    function edge(a){let sum=0,n=0;const end=Math.floor(w*0.46);for(let y=2;y<h-2;y++)for(let x=2;x<end;x++){const i=(y*w+x)*4;sum+=Math.abs(a[i]-a[i-4]);n++;}return sum/n;}
    const stats={w,h,...metric(original,enhanced),originalEdge:edge(original),enhancedEdge:edge(enhanced)};
    window.qualityFrames={original:Array.from(original),enhanced:Array.from(enhanced),w,h};
    return stats;
  });
  if(!old){
    assert.ok(result.enhancedEdge>result.originalEdge*1.12,'soft detail contrast must visibly increase: '+JSON.stringify(result));
    assert.ok(result.visibleFraction>.04,'at least 4% of channels must change by >=3/255: '+JSON.stringify(result));
    const split=await page.evaluate(()=>{
      document.querySelector('#realtimeSplit').click();const c=document.querySelector('#realtimeCanvas'),gl=c.getContext('webgl'),{w,h,original}=qualityFrames;
      const p=new Uint8Array(w*h*4);gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,p);let left=0,right=0,n=0;
      for(let y=0;y<h;y++)for(let x=0;x<w;x++)for(let k=0;k<3;k++){const d=Math.abs(p[((h-1-y)*w+x)*4+k]-original[(y*w+x)*4+k]);if(x<w/2)left+=d;else right+=d;n++;}return {left:left/(n/2),right:right/(n/2)};
    });
    assert.ok(split.left<1,'left side must show the same original frame: '+JSON.stringify(split));
    await page.evaluate(()=>{document.querySelector('#realtimeSplit').click();document.querySelector('#realtimeStrength').value=95;document.querySelector('#realtimeStrength').dispatchEvent(new Event('input',{bubbles:true}));});
    assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-strength'),'0.95');
  }
  await page.evaluate(old=>{
    renderer.destroy();const {w,h,original,enhanced}=qualityFrames;document.body.innerHTML='<div style="display:flex;width:max-content;gap:12px;padding:12px" id="results"></div>';
    for(const [label,data] of [['Original',original],[old?'Previous filter':'Adaptive enhancement 2.0',enhanced]]){const wrap=document.createElement('div'),title=document.createElement('p'),c=document.createElement('canvas');title.textContent=label;c.width=w;c.height=h;c.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(data),w,h),0,0);wrap.append(title,c);document.querySelector('#results').append(wrap);}
  },old);
  await page.locator('#results').screenshot({path:`${output}/quality-${width}-${old?'previous':'adaptive'}.png`});await context.close();return result;
}
try {
  for(const width of [390,1280]){
    const previous=baseline?await render(width,true):null,current=await render(width);
    if(previous)assert.ok(current.mean>previous.mean*1.5,'must improve the imperceptible previous filter: '+JSON.stringify({previous,current}));
    results.push({width,previous,current});
  }
  assert.deepEqual(errors,[]);console.log('REALTIME_QUALITY_UI=PASS '+JSON.stringify(results));
} finally {await browser.close()}

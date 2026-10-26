/*
Copyright (c) 2017-2019 Advanced Micro Devices, Inc. All rights reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
IN THE SOFTWARE.
*/
/* Non-AI, display-only sharpening. The existing video remains the sole A/V clock. */
(() => {
  'use strict';
  const KEY = 'tvm-realtime-enhancement-v1';
  const modes = {off: ['关闭', 0], natural: ['自然', .35], clear: ['清晰', .7], strong: ['较强', 1], custom: ['自定义', .7]};
  const vertex = `attribute vec2 position; varying vec2 uv;
    void main(){uv=(position+1.0)*0.5;gl_Position=vec4(position,0.0,1.0);}`;
  // Luma adaptation of AMD FidelityFX CAS (MIT; see THIRD_PARTY_NOTICES.md).
  // Sample the displayed pixel footprint so downscaling does not erase the effect.
  const fragment = `#ifdef GL_FRAGMENT_PRECISION_HIGH
    precision highp float;
    #else
    precision mediump float;
    #endif
    varying vec2 uv;
    uniform sampler2D picture; uniform vec2 pixel; uniform float amount; uniform float split;
    float luma(vec3 p){return dot(p,vec3(0.299,0.587,0.114));}
    float light(vec2 p){vec3 c=texture2D(picture,p).rgb;return luma(c*c);}
    void main(){
      vec3 c=texture2D(picture,uv).rgb;
      if(uv.x<split){gl_FragColor=vec4(c,1.0);return;}
      float y=luma(c*c);
      float n=light(uv+vec2(0.0,pixel.y));
      float s=light(uv-vec2(0.0,pixel.y));
      float e=light(uv+vec2(pixel.x,0.0));
      float w=light(uv-vec2(pixel.x,0.0));
      float lo=min(y,min(min(n,s),min(e,w)));
      float hi=max(y,max(max(n,s),max(e,w)));
      float adaptive=sqrt(clamp(min(lo,1.0-hi)/max(hi,0.0001),0.0,1.0));
      float weight=-adaptive/mix(8.0,5.0,amount);
      float sharp=(y+weight*(n+s+e+w))/(1.0+4.0*weight);
      // Wider local contrast makes soft, low-frequency details visible as well.
      vec2 wide=pixel*3.0;
      float mean=(light(uv+vec2(wide.x,0.0))+light(uv-vec2(wide.x,0.0))+
        light(uv+vec2(0.0,wide.y))+light(uv-vec2(0.0,wide.y)))*0.25;
      float local=clamp((y-mean)*amount*0.18,-0.025,0.025);
      float noise=smoothstep(0.002,0.025,hi-lo);
      float restored=clamp(y+(sharp-y)*amount*mix(0.4,1.0,noise)+local,0.0,1.0);
      // Bound luminance changes and retain chroma differences instead of boosting saturation.
      float delta=clamp(sqrt(restored)-sqrt(y),-0.12,0.12);
      gl_FragColor=vec4(clamp(c+vec3(delta),0.0,1.0),1.0);
    }`;

  window.attachRealtimeEnhancement = ({shell, stage, video, changed}) => {
    const button = shell.querySelector('#realtimeButton'), openButton = shell.querySelector('#realtimeOpen');
    const panel = shell.querySelector('#realtimePanel'), status = shell.querySelector('#realtimeStatus');
    const detail = shell.querySelector('#realtimeDetail'), compare = shell.querySelector('#realtimeCompare');
    const strengthInput = shell.querySelector('#realtimeStrength'), strengthValue = shell.querySelector('#realtimeStrengthValue');
    const splitButtons = [shell.querySelector('#realtimeSplit'),shell.querySelector('#realtimeSplitQuick')];
    const splitInput = shell.querySelector('#realtimeSplitPosition'), splitControls = shell.querySelector('#realtimeSplitControls');
    const labels = document.createElement('div'); labels.className='realtime-frame-labels'; labels.hidden=true;
    labels.innerHTML='<span>原画</span><span>增强</span><i></i>';stage.appendChild(labels);
    const canvas = document.createElement('canvas');
    canvas.id = 'realtimeCanvas'; canvas.className = 'realtime-canvas'; canvas.hidden = true;
    canvas.setAttribute('aria-hidden', 'true'); stage.insertBefore(canvas, video.nextSibling);
    let mode = 'off';
    try { const saved = localStorage.getItem(KEY); if (Object.hasOwn(modes, saved)) mode = saved; } catch {}
    let strength = modes[mode][1];
    if(mode==='custom')try{const saved=Number(localStorage.getItem(KEY+'-strength'));if(Number.isFinite(saved))strength=Math.max(.01,Math.min(1,saved));}catch{}
    let splitting=false, splitAt=.5;
    let gl, program, texture, buffer, pixelLocation, amountLocation, splitLocation;
    let disposed = false, blocked = '', comparing = false, nativeFullscreen = false;
    let callback = null, callbackKind, lastTime = -1, frames = 0, slow = 0, suspended = '';
    const removers = [];
    const on = (node, event, handler, options) => {
      node.addEventListener(event, handler, options);
      removers.push(() => node.removeEventListener(event, handler, options));
    };
    const stop = () => {
      if (callback !== null) {
        if (callbackKind === 'video') video.cancelVideoFrameCallback?.(callback);
        else cancelAnimationFrame(callback);
        callback = null;
      }
    };
    const revealOriginal = () => {
      canvas.hidden = true; stage.classList.remove('realtime-active');
      labels.hidden = true;
      canvas.dataset.active = 'false';
    };
    const reason = () => blocked || suspended || (comparing ? '正在对比原画' : '');
    function paint() {
      const label = modes[mode][0];
      const active = mode !== 'off' && !reason();
      const unavailable=Boolean(blocked||suspended);
      button.textContent = mode === 'off' ? '增强' : unavailable ? '原画' : mode==='custom' ? Math.round(strength*100)+'%' : label;
      button.classList.toggle('realtime-selected', active);
      button.setAttribute('aria-label', `实时增强：${label}，打开设置`);
      button.setAttribute('aria-pressed', String(mode !== 'off'));
      button.setAttribute('aria-expanded', String(!panel.hidden));
      openButton.textContent = mode === 'off' ? '开启增强' : '调整增强';
      status.textContent = reason() || (mode === 'off' ? '不额外存片 · 开启即生效' : `${label} ${Math.round(strength*100)}% · ${splitting?'左右对比中':canvas.hidden?'等待画面':'正在增强'}`);
      detail.textContent = reason() || '自适应锐化 + 局部对比度；较强档可能放大噪点。仅处理画面，不另存视频。';
      compare.disabled = mode === 'off' || Boolean(blocked || suspended);
      strengthInput.value=String(Math.round(strength*100));strengthValue.textContent=strengthInput.value+'%';
      splitButtons.forEach(node=>{node.disabled=mode==='off'||unavailable;node.setAttribute('aria-pressed',String(splitting));node.textContent=splitting?'退出对比':'左右对比';});
      splitControls.hidden=!splitting;
      panel.querySelectorAll('[data-realtime-mode]').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.realtimeMode === mode)));
      canvas.dataset.mode = mode;
      canvas.dataset.strength=String(strength);canvas.dataset.algorithm='adaptive-cas-v2';canvas.dataset.split=String(splitting);
    }
    const fail = message => { stop(); revealOriginal(); blocked = message; paint(); };
    function init() {
      if (gl && program && !gl.isContextLost()) return true;
      try {
        gl = canvas.getContext('webgl', {alpha:false, antialias:false, depth:false, stencil:false, powerPreference:'low-power'});
        if (!gl) throw Error('WebGL unavailable');
        const compile = (kind, source) => {
          const shader = gl.createShader(kind); gl.shaderSource(shader, source); gl.compileShader(shader);
          if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) { gl.deleteShader(shader); throw Error('Shader unavailable'); }
          return shader;
        };
        const vs = compile(gl.VERTEX_SHADER, vertex), fs = compile(gl.FRAGMENT_SHADER, fragment);
        program = gl.createProgram(); gl.attachShader(program, vs); gl.attachShader(program, fs); gl.linkProgram(program);
        gl.deleteShader(vs); gl.deleteShader(fs);
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error('Renderer unavailable');
        gl.useProgram(program);
        buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,1,1]), gl.STATIC_DRAW);
        const position = gl.getAttribLocation(program, 'position');
        gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
        texture = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
        pixelLocation = gl.getUniformLocation(program, 'pixel'); amountLocation = gl.getUniformLocation(program, 'amount');splitLocation=gl.getUniformLocation(program,'split');
        gl.uniform1i(gl.getUniformLocation(program, 'picture'), 0);
        return true;
      } catch {
        if (gl) {gl.deleteTexture(texture);gl.deleteBuffer(buffer);gl.deleteProgram(program);}
        program = texture = buffer = null;
        fail('当前浏览器无法实时增强，继续播放原画'); return false;
      }
    }
    function canDraw() {
      return !disposed && mode !== 'off' && !reason() && !document.hidden && !video.seeking && video.readyState >= 2 && video.videoWidth > 0;
    }
    function draw(mediaTime = video.currentTime) {
      if (!canDraw()) return false;
      if (!init()) return false;
      const started = performance.now();
      try {
        const w = video.videoWidth, h = video.videoHeight;
        if (Math.max(w,h) > gl.getParameter(gl.MAX_TEXTURE_SIZE)) throw Error('Texture too large');
        // Match the actual display surface: avoid sharpening then rescaling again.
        const dpr = Math.min(devicePixelRatio || 1, 2);
        const fit=Math.min(stage.clientWidth/w,stage.clientHeight/h);
        const scale = Math.min(fit*dpr,Math.sqrt(4194304/(w*h)),4096/Math.max(w,h));
        const width = Math.max(1, Math.round(w * scale)), height = Math.max(1, Math.round(h * scale));
        if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
        gl.viewport(0,0,width,height);
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,video);
        gl.uniform2f(pixelLocation,Math.max(1/w,1/width),Math.max(1/h,1/height));gl.uniform1f(amountLocation,strength);gl.uniform1f(splitLocation,splitting?splitAt:-1);
        gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
        if (gl.getError() !== gl.NO_ERROR) throw Error('Frame unavailable');
        canvas.hidden = false; stage.classList.add('realtime-active');
        canvas.dataset.active = 'true'; canvas.dataset.frames = String(++frames);
        canvas.dataset.frameTime = String(mediaTime);
        labels.hidden=!splitting;
        labels.style.cssText=`left:${(stage.clientWidth-w*fit)/2}px;top:${(stage.clientHeight-h*fit)/2}px;width:${w*fit}px;height:${h*fit}px;--split:${splitAt*100}%`;
        const cost = performance.now() - started;
        slow = cost > 45 ? slow + 1 : Math.max(0,slow-1);
        if (slow >= 8) { fail('设备负载较高，已恢复原画；可关闭增强或稍后重试'); return false; }
        lastTime = video.currentTime;
        return true;
      } catch { fail('实时增强暂不可用，已恢复原画'); return false; }
    }
    function schedule() {
      if (!canDraw() || video.paused || video.ended || callback !== null) return;
      if (video.requestVideoFrameCallback) {
        callbackKind = 'video';
        callback = video.requestVideoFrameCallback((_now, metadata) => {
          callback = null;
          if (draw(metadata.mediaTime)) schedule();
        });
      } else {
        callbackKind = 'animation';
        callback = requestAnimationFrame(() => {
          callback = null;
          if (!canDraw()) return;
          if (video.currentTime !== lastTime) draw();
          schedule();
        });
      }
    }
    const refresh = () => { if (disposed) return; stop(); if (draw()) schedule(); paint(); };
    const presentation = () => {
      suspended = document.pictureInPictureElement === video || video.webkitPresentationMode === 'picture-in-picture' ? '画中画显示原画'
        : nativeFullscreen || video.webkitDisplayingFullscreen || video.webkitPresentationMode === 'fullscreen' ? '系统视频全屏显示原画' : '';
      if (suspended) { stop(); revealOriginal(); paint(); } else refresh();
    };
    function setMode(next, customStrength) {
      if (!Object.hasOwn(modes,next) || disposed) return;
      mode = next; blocked = ''; slow = 0; comparing = false;
      strength=next==='custom'?(Number.isFinite(customStrength)?Math.max(.01,Math.min(1,customStrength)):strength):modes[next][1];
      if(next==='off')splitting=false;
      try { localStorage.setItem(KEY,mode);localStorage.setItem(KEY+'-strength',String(strength)); } catch {}
      stop(); revealOriginal(); refresh(); changed?.();
    }
    const close = () => { panel.hidden = true; comparing = false; refresh(); paint(); changed?.(); };
    const toggle = () => { panel.hidden = !panel.hidden; paint(); changed?.(); };
    button.onclick = openButton.onclick = toggle;
    shell.querySelector('#realtimeClose').onclick = close;
    panel.querySelectorAll('[data-realtime-mode]').forEach(node => { node.onclick = () => setMode(node.dataset.realtimeMode); });
    on(strengthInput,'input',()=>{const value=Number(strengthInput.value)/100;setMode(value>0?'custom':'off',value);});
    splitButtons.forEach(node=>{node.onclick=()=>{splitting=!splitting;refresh();changed?.();};});
    on(splitInput,'input',()=>{splitAt=Number(splitInput.value)/100;refresh();});
    const beginCompare = () => { if (compare.disabled) return; comparing = true; stop(); revealOriginal(); paint(); };
    const endCompare = () => { if (!comparing) return; comparing = false; refresh(); };
    on(compare,'pointerdown',event => { if (event.button !== 0) return; event.preventDefault(); compare.setPointerCapture?.(event.pointerId); beginCompare(); });
    on(window,'pointerup',endCompare); on(window,'pointercancel',endCompare); on(window,'blur',endCompare);
    on(compare,'keydown',event => { if (['Space','Enter'].includes(event.code)) {event.preventDefault();beginCompare();} });
    on(compare,'keyup',endCompare); on(compare,'blur',endCompare);
    on(video,'play',refresh); on(video,'playing',refresh); on(video,'loadeddata',refresh); on(video,'seeked',refresh);
    on(video,'pause',refresh); on(video,'ended',refresh); on(video,'resize',refresh);
    const reset = () => { stop(); revealOriginal(); lastTime = -1; paint(); };
    on(video,'seeking',reset); on(video,'emptied',reset); on(video,'loadstart',reset); on(video,'error',reset);
    on(video,'enterpictureinpicture',presentation); on(video,'leavepictureinpicture',presentation);
    on(video,'webkitpresentationmodechanged',presentation);
    on(video,'webkitbeginfullscreen',() => {nativeFullscreen=true;presentation();});
    on(video,'webkitendfullscreen',() => {nativeFullscreen=false;presentation();});
    on(document,'visibilitychange',() => {if(document.hidden){stop();revealOriginal();}else refresh();});
    on(document,'fullscreenchange',refresh);
    on(canvas,'webglcontextlost',event => {event.preventDefault();if(!disposed)fail('图形资源暂不可用，已恢复原画');});
    on(canvas,'webglcontextrestored',() => {gl=null;if(!disposed){blocked='';refresh();}});
    on(document,'pointerdown',event => {if(!panel.hidden&&!panel.contains(event.target)&&!button.contains(event.target)&&!openButton.contains(event.target))close();},true);
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(refresh) : null;
    observer?.observe(stage);
    paint(); refresh();
    return {setMode,close,isOpen:()=>!panel.hidden,destroy(){
      disposed=true;stop();observer?.disconnect();removers.forEach(remove=>remove());revealOriginal();
      if(gl){gl.deleteTexture(texture);gl.deleteBuffer(buffer);gl.deleteProgram(program);gl.getExtension('WEBGL_lose_context')?.loseContext();}
      canvas.width=canvas.height=1;canvas.remove();labels.remove();
    }};
  };
})();

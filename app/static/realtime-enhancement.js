/* Non-AI, display-only sharpening. The existing video remains the sole A/V clock. */
(() => {
  'use strict';
  const KEY = 'tvm-realtime-enhancement-v1';
  const modes = {off: ['关闭', 0], natural: ['自然', .22], clear: ['清晰', .45], strong: ['较强', .7]};
  const vertex = `attribute vec2 position; varying vec2 uv;
    void main(){uv=(position+1.0)*0.5;gl_Position=vec4(position,0.0,1.0);}`;
  // A bounded luma-only high-pass avoids sharpening chroma noise or adding halos.
  const fragment = `#ifdef GL_FRAGMENT_PRECISION_HIGH
    precision highp float;
    #else
    precision mediump float;
    #endif
    varying vec2 uv;
    uniform sampler2D picture; uniform vec2 pixel; uniform float amount;
    float luma(vec3 p){return dot(p,vec3(0.299,0.587,0.114));}
    void main(){
      vec3 c=texture2D(picture,uv).rgb;
      float y=luma(c);
      float n=luma(texture2D(picture,uv+vec2(0.0,pixel.y)).rgb);
      float s=luma(texture2D(picture,uv-vec2(0.0,pixel.y)).rgb);
      float e=luma(texture2D(picture,uv+vec2(pixel.x,0.0)).rgb);
      float w=luma(texture2D(picture,uv-vec2(pixel.x,0.0)).rgb);
      float lo=min(y,min(min(n,s),min(e,w)));
      float hi=max(y,max(max(n,s),max(e,w)));
      float detail=y-(n+s+e+w)*0.25;
      float gate=smoothstep(0.012,0.075,hi-lo);
      float delta=clamp(detail*amount*2.0*gate,-0.055,0.055);
      float restored=clamp(y+delta,lo-0.012,hi+0.012);
      gl_FragColor=vec4(clamp(c+vec3(restored-y),0.0,1.0),1.0);
    }`;

  window.attachRealtimeEnhancement = ({shell, stage, video, changed}) => {
    const button = shell.querySelector('#realtimeButton'), openButton = shell.querySelector('#realtimeOpen');
    const panel = shell.querySelector('#realtimePanel'), status = shell.querySelector('#realtimeStatus');
    const detail = shell.querySelector('#realtimeDetail'), compare = shell.querySelector('#realtimeCompare');
    const canvas = document.createElement('canvas');
    canvas.id = 'realtimeCanvas'; canvas.className = 'realtime-canvas'; canvas.hidden = true;
    canvas.setAttribute('aria-hidden', 'true'); stage.insertBefore(canvas, video.nextSibling);
    let mode = 'off';
    try { const saved = localStorage.getItem(KEY); if (Object.hasOwn(modes, saved)) mode = saved; } catch {}
    let gl, program, texture, buffer, pixelLocation, amountLocation;
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
      canvas.dataset.active = 'false';
    };
    const reason = () => blocked || suspended || (comparing ? '正在对比原画' : '');
    function paint() {
      const label = modes[mode][0];
      const active = mode !== 'off' && !reason();
      button.textContent = mode === 'off' ? '增强' : label;
      button.classList.toggle('realtime-selected', active);
      button.setAttribute('aria-label', `实时增强：${label}，打开设置`);
      button.setAttribute('aria-pressed', String(mode !== 'off'));
      button.setAttribute('aria-expanded', String(!panel.hidden));
      openButton.textContent = mode === 'off' ? '选择实时增强' : '实时增强 · ' + label;
      status.textContent = reason() || (mode === 'off' ? '不额外存片 · 开启即生效' : `${label} · 仅当前播放画面生效`);
      detail.textContent = reason() || '仅增强播放画面，不生成视频副本；下载保留所选源文件。';
      compare.disabled = mode === 'off' || Boolean(blocked || suspended);
      panel.querySelectorAll('[data-realtime-mode]').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.realtimeMode === mode)));
      canvas.dataset.mode = mode;
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
        pixelLocation = gl.getUniformLocation(program, 'pixel'); amountLocation = gl.getUniformLocation(program, 'amount');
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
        // Never enlarge source pixels. Limit the display surface, not the source texture.
        const dpr = Math.min(devicePixelRatio || 1, 2);
        const scale = Math.min(1, Math.min(stage.clientWidth / w, stage.clientHeight / h) * dpr);
        const width = Math.max(1, Math.round(w * scale)), height = Math.max(1, Math.round(h * scale));
        if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
        gl.viewport(0,0,width,height);
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,video);
        gl.uniform2f(pixelLocation,1/w,1/h); gl.uniform1f(amountLocation,modes[mode][1]);
        gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
        if (gl.getError() !== gl.NO_ERROR) throw Error('Frame unavailable');
        canvas.hidden = false; stage.classList.add('realtime-active');
        canvas.dataset.active = 'true'; canvas.dataset.frames = String(++frames);
        canvas.dataset.frameTime = String(mediaTime);
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
    function setMode(next) {
      if (!Object.hasOwn(modes,next) || disposed) return;
      mode = next; blocked = ''; slow = 0; comparing = false;
      try { localStorage.setItem(KEY,mode); } catch {}
      stop(); revealOriginal(); refresh(); changed?.();
    }
    const close = () => { panel.hidden = true; comparing = false; refresh(); paint(); changed?.(); };
    const toggle = () => { panel.hidden = !panel.hidden; paint(); changed?.(); };
    button.onclick = openButton.onclick = toggle;
    shell.querySelector('#realtimeClose').onclick = close;
    panel.querySelectorAll('[data-realtime-mode]').forEach(node => { node.onclick = () => setMode(node.dataset.realtimeMode); });
    const beginCompare = () => { if (compare.disabled) return; comparing = true; stop(); revealOriginal(); paint(); };
    const endCompare = () => { if (!comparing) return; comparing = false; refresh(); };
    on(compare,'pointerdown',event => { if (event.button !== 0) return; event.preventDefault(); compare.setPointerCapture?.(event.pointerId); beginCompare(); });
    on(window,'pointerup',endCompare); on(window,'pointercancel',endCompare); on(window,'blur',endCompare);
    on(compare,'keydown',event => { if (['Space','Enter'].includes(event.code)) {event.preventDefault();beginCompare();} });
    on(compare,'keyup',endCompare); on(compare,'blur',endCompare);
    on(video,'play',refresh); on(video,'playing',refresh); on(video,'loadeddata',refresh); on(video,'seeked',refresh);
    on(video,'pause',refresh); on(video,'ended',refresh); on(video,'resize',refresh);
    const reset = () => { stop(); revealOriginal(); lastTime = -1; };
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
      canvas.width=canvas.height=1;canvas.remove();
    }};
  };
})();

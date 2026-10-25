/* Real fragment bytes (HLS) or playable seconds (native video), never a timed counter. */
(function (scope) {
  'use strict';
  scope.attachPlayerBuffer = function ({ video, node, spinner }) {
    const listeners = [];
    let timer = null, hideTimer = null, active = false, stopped = false, target = 0, fragment = null;
    let fragments = [], hlsRemove = [], phase = '正在准备画面';
    node.innerHTML = '<span class="buffer-caption"></span><strong class="buffer-percent">0%</strong><div class="buffer-meter" role="progressbar" aria-label="当前画面加载进度" aria-valuemin="0" aria-valuemax="100"><i></i></div>';
    const caption = node.querySelector('.buffer-caption'), percent = node.querySelector('.buffer-percent');
    const meter = node.querySelector('.buffer-meter'), fill = meter.firstElementChild;
    const on = (name, fn) => { video.addEventListener(name, fn); listeners.push(() => video.removeEventListener(name, fn)); };
    const contains = frag => frag && Number.isFinite(frag.start) && Number.isFinite(frag.duration)
      && target >= frag.start - .05 && target < frag.start + frag.duration;
    const paint = () => {
      if (!active || stopped) return;
      let end = target;
      for (let i = 0; i < video.buffered.length; i++) {
        if (video.buffered.start(i) <= target + .05 && video.buffered.end(i) >= target) end = Math.max(end, video.buffered.end(i));
      }
      const goal = Math.max(.05, Math.min(3, (Number(video.duration) || target + 3) - target));
      const seconds = Math.max(0, end - target);
      const stats = contains(fragment) ? (fragment.loader?.stats || fragment.stats) : null;
      let value = Math.min(100, Math.floor(seconds / goal * 100)), detail = `已缓冲 ${Math.min(goal, seconds).toFixed(1)} / ${goal.toFixed(1)} 秒`;
      if (stats?.total > 0 && seconds < goal) {
        value = Math.min(100, Math.floor(stats.loaded / stats.total * 100));
        detail = value === 100 ? '片段已接收 · 正在解码' : '正在接收目标画面';
      }
      percent.textContent = `${value}%`; fill.style.width = `${value}%`;
      caption.textContent = `${phase} · ${detail}`;
      meter.setAttribute('aria-valuenow', String(value));
      node.dataset.percent = String(value);
    };
    const start = (at = video.currentTime, label = '正在缓冲') => {
      if (stopped) return;
      clearTimeout(hideTimer); clearInterval(timer);
      target = Number(at) || 0; phase = label; active = true;
      fragment = fragments.find(contains) || null;
      node.hidden = false; spinner?.classList.add('show');
      paint(); timer = setInterval(paint, 150);
    };
    const finish = () => {
      if (!active || stopped || video.seeking) return;
      clearInterval(timer); active = false;
      percent.textContent = '100%'; fill.style.width = '100%'; meter.setAttribute('aria-valuenow', '100'); node.dataset.percent = '100';
      caption.textContent = '画面已就绪'; spinner?.classList.remove('show');
      hideTimer = setTimeout(() => { node.hidden = true; }, 350);
    };
    const hide = () => { active = false; clearInterval(timer); clearTimeout(hideTimer); node.hidden = true; spinner?.classList.remove('show'); };
    const unbind = () => { hlsRemove.forEach(remove => remove()); hlsRemove = []; fragment = null; fragments = []; };
    on('seeking', () => start(video.currentTime, '正在定位画面'));
    on('waiting', () => start(video.currentTime));
    on('progress', paint); on('loadeddata', paint);
    on('seeked', () => { if (video.readyState >= 3) finish(); else paint(); });
    on('canplay', finish); on('playing', finish); on('error', hide); on('ended', hide);
    return {
      reset(at) { unbind(); start(at, '正在准备画面'); },
      bind(instance, events) {
        unbind();
        // Remember in-flight prefetches too: waiting can occur after FRAG_LOADING.
        const load = (_event, data) => {
          fragments = [data.frag, ...fragments.filter(frag => frag !== data.frag)].slice(0, 8);
          if (active && contains(data.frag)) { fragment = data.frag; paint(); }
        };
        for (const event of [events.FRAG_LOADING, events.FRAG_LOADED]) { instance.on(event, load); hlsRemove.push(() => instance.off(event, load)); }
      },
      hide,
      destroy() { stopped = true; hide(); unbind(); listeners.forEach(remove => remove()); },
    };
  };
})(window);

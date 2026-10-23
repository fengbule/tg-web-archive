/* One video element owns both audio and video throughout every gesture. */
(function (scope) {
  'use strict';
  scope.attachMediaScrubber = function ({ video, input, stage, preview, finish, changed }) {
    const listeners = [];
    let timer = null, pending = null, dragging = false;
    let resume = false, gesture = null, suppressClickUntil = 0;
    const on = (node, event, callback, options) => {
      node.addEventListener(event, callback, options);
      listeners.push(() => node.removeEventListener(event, callback, options));
    };
    const clamp = time => Math.max(0, Math.min(Math.max(0, (video.duration || 0) - .05), time));
    const apply = () => {
      clearTimeout(timer); timer = null;
      if (pending === null || !Number.isFinite(video.duration)) return;
      const target = pending; pending = null;
      video.currentTime = target;
      changed?.(target);
    };
    const request = time => {
      pending = clamp(time);
      preview(pending, true);
      // Show thumbnails on every move, but don't repeatedly fetch abandoned
      // full-quality GOPs. A brief hold seeks while pressed; release flushes.
      clearTimeout(timer);
      timer = setTimeout(apply, 180);
    };
    const begin = () => {
      if (dragging) return;
      dragging = true; resume = !video.paused;
      video.pause();
    };
    const end = () => {
      if (!dragging) { apply(); finish(); return; }
      apply(); dragging = false; finish();
      if (resume) video.play().catch(() => {});
    };
    on(input, 'pointerdown', begin);
    on(input, 'input', () => request(Number(input.value) / Number(input.max) * video.duration));
    on(input, 'change', end);
    on(scope, 'pointerup', () => { if (!gesture && dragging) end(); });
    on(scope, 'pointercancel', () => { if (dragging) end(); gesture = null; });
    on(input, 'blur', () => { if (dragging) end(); });
    on(stage, 'pointerdown', event => {
      if (event.pointerType === 'mouse' || event.target.closest('button,a,input')) return;
      gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, at: video.currentTime, active: false };
    });
    on(stage, 'pointermove', event => {
      if (!gesture || event.pointerId !== gesture.id) return;
      const dx = event.clientX - gesture.x, dy = event.clientY - gesture.y;
      if (!gesture.active) {
        if (Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > 10) { gesture = null; return; }
        if (Math.abs(dx) < 10) return;
        gesture.active = true; begin();
        stage.setPointerCapture(event.pointerId);
      }
      event.preventDefault();
      const span = Math.min(video.duration || 0, 120);
      request(gesture.at + dx / Math.max(stage.clientWidth, 1) * span);
    }, { passive: false });
    on(stage, 'pointerup', event => {
      if (!gesture || event.pointerId !== gesture.id) return;
      if (gesture.active) { suppressClickUntil = performance.now() + 500; end(); }
      gesture = null;
    });
    on(stage, 'click', event => {
      if (performance.now() < suppressClickUntil) { event.stopPropagation(); event.preventDefault(); suppressClickUntil = 0; }
    }, true);
    return {
      dragging: () => dragging,
      destroy() { clearTimeout(timer); listeners.forEach(remove => remove()); },
    };
  };
})(window);

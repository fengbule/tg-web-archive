/* Tapping the picture only toggles controls; playback has its own button. */
(function (scope) {
  'use strict';
  scope.attachPlayerControls = function ({ shell, stage, video, scrubbing, interacting }) {
    const listeners = [], pointers = new Set();
    let timer = null, hovering = false, keyboard = false;
    const controls = shell.querySelector('.player-controls');
    const on = (node, event, callback, options) => {
      node.addEventListener(event, callback, options);
      listeners.push(() => node.removeEventListener(event, callback, options));
    };
    const busy = () => video.paused || video.ended || pointers.size || hovering || scrubbing?.() || interacting?.()
      || (keyboard && shell.contains(document.activeElement));
    const hide = () => {
      clearTimeout(timer);
      if (!busy()) shell.classList.add('controls-hidden');
    };
    const show = () => {
      clearTimeout(timer);
      shell.classList.remove('controls-hidden');
      if (!busy()) timer = setTimeout(hide, 3000);
    };
    on(stage, 'click', event => {
      if (event.defaultPrevented || event.target.closest('button,a,input')) return;
      if (shell.classList.contains('controls-hidden') || busy()) show();
      else hide();
    });
    // The hidden dock keeps its space, so revealing it never resizes the video.
    on(shell, 'click', event => { if (event.target === shell) show(); });
    on(shell, 'pointermove', event => { if (event.pointerType === 'mouse') show(); });
    on(shell, 'pointerdown', event => {
      keyboard = false; pointers.add(event.pointerId);
      // A tap on the picture must reach the click handler with its prior state.
      if (!stage.contains(event.target)) show();
      else clearTimeout(timer);
    }, true);
    const release = event => { if (pointers.delete(event.pointerId) && !shell.classList.contains('controls-hidden')) show(); };
    on(scope, 'pointerup', release);
    on(scope, 'pointercancel', event => { pointers.delete(event.pointerId); show(); });
    on(controls, 'pointerenter', event => { if (event.pointerType === 'mouse') { hovering = true; show(); } });
    on(controls, 'pointerleave', event => { if (event.pointerType === 'mouse') { hovering = false; show(); } });
    on(document, 'keydown', event => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      keyboard = true; show();
    });
    on(shell, 'focusin', () => { if (keyboard) show(); });
    on(shell, 'focusout', () => { if (keyboard) { clearTimeout(timer); timer = setTimeout(show, 0); } });
    on(video, 'play', show);
    on(video, 'playing', show);
    on(video, 'pause', show);
    on(video, 'ended', show);
    on(document, 'fullscreenchange', show);
    show();
    return {
      show,
      destroy() { clearTimeout(timer); listeners.forEach(remove => remove()); pointers.clear(); },
    };
  };
})(window);

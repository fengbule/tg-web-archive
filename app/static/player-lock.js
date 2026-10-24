/* Lock the viewing direction without disabling seeking or episode controls. */
(function (scope) {
  'use strict';
  scope.attachPlayerLock = function ({ shell, button, changed, notice }) {
    const listeners = [];
    let locked = false, disposed = false, run = 0, ownsFullscreen = false, requestedOrientation = false;
    let layout = 'portrait', angle = null, native = false, home = null, deviceAligned = false, pageOverflow = null;
    const orientation = scope.screen?.orientation;
    const on = (node, event, callback) => {
      node?.addEventListener?.(event, callback);
      listeners.push(() => node?.removeEventListener?.(event, callback));
    };
    const currentAngle = () => {
      const value = Number.isFinite(orientation?.angle) ? orientation.angle : scope.orientation;
      return Number.isFinite(value) ? value : null;
    };
    const reflow = () => {
      if (!locked) return;
      const width = scope.innerWidth, height = scope.innerHeight;
      const now = currentAngle();
      let rotation = angle !== null && now !== null ? (angle - now + 540) % 360 - 180 : 0;
      // A phone keyboard can make a portrait viewport wider than it is tall.
      // Use the physical direction when it matched the viewport on entry.
      const flipped = deviceAligned && angle !== null && now !== null ? Math.abs(rotation) % 180 === 90
        : (width > height ? 'landscape' : 'portrait') !== layout;
      shell.dataset.keyboardOpen = String(deviceAligned && !flipped && layout === 'portrait' && height < width);
      // Viewport-only browsers can report an unchanged screen angle. Keep the
      // player's chosen layout even there, without starting a second video.
      if (flipped !== (Math.abs(rotation) % 180 === 90)) rotation = flipped ? -90 : 0;
      shell.style.setProperty('--locked-width', (flipped ? height : width) + 'px');
      shell.style.setProperty('--locked-height', (flipped ? width : height) + 'px');
      shell.style.setProperty('--locked-rotation', rotation + 'deg');
    };
    const paint = () => {
      shell.classList.toggle('is-locked', locked);
      shell.dataset.lockLayout = layout;
      shell.dataset.lockMethod = locked ? native ? 'native' : 'layout' : 'none';
      button.setAttribute('aria-pressed', String(locked));
      button.setAttribute('aria-label', locked ? '解锁界面方向' : '锁定界面方向');
      button.title = locked ? '解锁界面方向' : '锁定界面方向，仍可快进和选集';
      button.querySelector('use')?.setAttribute('href', locked ? '#i-lock' : '#i-unlock');
      shell.querySelectorAll('[data-lock-disable]').forEach(node => { node.inert = locked; });
      const status = shell.querySelector('#lockStatus');
      if (status) { status.hidden = !locked; status.textContent = native ? '方向已锁定' : '画面方向已固定'; }
      if (locked) reflow();
      else for (const name of ['width', 'height', 'rotation']) shell.style.removeProperty('--locked-' + name);
      if (!locked) delete shell.dataset.keyboardOpen;
      changed?.(locked);
    };
    const releaseOrientation = () => {
      if (!requestedOrientation) return;
      requestedOrientation = false;
      try { orientation?.unlock?.(); } catch {}
    };
    const restoreHome = () => {
      if (home?.parentNode) { home.replaceWith(shell); home = null; }
    };
    const restoreScroll = () => {
      if (pageOverflow !== null) { document.documentElement.style.overflow = pageOverflow; pageOverflow = null; }
    };
    const setLocked = async value => {
      if (disposed || locked === value) return;
      const epoch = ++run;
      locked = value; native = false;
      if (!value) {
        releaseOrientation();
        restoreScroll();
        const exit = ownsFullscreen && document.fullscreenElement === shell;
        ownsFullscreen = false; paint();
        if (exit) { try { await document.exitFullscreen(); } catch {} }
        if (!locked) restoreHome();
        return;
      }
      layout = scope.innerWidth > scope.innerHeight ? 'landscape' : 'portrait';
      pageOverflow = document.documentElement.style.overflow;
      document.documentElement.style.overflow = 'hidden';
      angle = currentAngle();
      deviceAligned = orientation?.type ? orientation.type.startsWith(layout) : angle !== null;
      paint();
      if (!document.fullscreenElement && !home) {
        home = document.createComment('player-lock-home');
        shell.before(home); document.body.append(shell);
      }
      const target = orientation?.type?.startsWith(layout) ? orientation.type : layout;
      // Calling requestFullscreen while handling the button preserves user activation.
      if (!document.fullscreenElement && shell.requestFullscreen) {
        try {
          await shell.requestFullscreen();
          if (disposed || epoch !== run) {
            if (!locked && document.fullscreenElement === shell) await document.exitFullscreen();
            return;
          }
          ownsFullscreen = true;
        } catch {}
      }
      if (disposed || epoch !== run) return;
      try {
        if (!orientation?.lock) throw new Error('Orientation lock unavailable');
        requestedOrientation = true;
        await orientation.lock(target);
        if (disposed || epoch !== run) { if (!locked) releaseOrientation(); return; }
        native = true; paint();
        notice?.('已锁定当前方向，仍可快进、拖动和选集');
      } catch {
        if (disposed || epoch !== run) return;
        paint();
        notice?.('已固定播放器方向，仍可快进和选集；系统状态栏方向由手机控制');
      }
    };
    on(button, 'click', () => { void setLocked(!locked); });
    on(scope, 'resize', reflow);
    on(scope, 'orientationchange', reflow);
    on(orientation, 'change', reflow);
    on(document, 'fullscreenchange', () => {
      if (locked && !document.fullscreenElement) { native = false; ownsFullscreen = false; paint(); }
      else reflow();
    });
    return {
      isLocked: () => locked,
      setLocked,
      destroy() {
        disposed = true; ++run; locked = false; native = false;
        listeners.forEach(remove => remove()); releaseOrientation(); paint();
        if (ownsFullscreen && document.fullscreenElement === shell) document.exitFullscreen().catch(() => {});
        restoreHome(); restoreScroll();
      },
    };
  };
})(window);

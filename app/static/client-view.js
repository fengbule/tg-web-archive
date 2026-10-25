/* Apply the saved layout before paint; changing it never recreates a page/player. */
(function () {
  'use strict';
  const root = document.documentElement, key = 'nebula-view-mode';
  const modes = ['auto', 'phone', 'tablet', 'desktop'];
  const names = {auto:'自动', phone:'手机', tablet:'平板', desktop:'电脑'};
  let mode = 'auto';
  try { mode = localStorage.getItem(key) || mode; } catch {}
  if (!modes.includes(mode)) mode = 'auto';
  function apply() {
    const layout = mode === 'auto' ? (innerWidth < 680 ? 'phone' : innerWidth < 1180 ? 'tablet' : 'desktop') : mode;
    root.dataset.viewMode = mode; root.dataset.layout = layout;
    const label = document.querySelector('#viewModeLabel');
    if (label) label.textContent = names[mode] + (mode === 'auto' ? ' · ' + names[layout] : '模式');
    document.querySelectorAll('[data-view-choice]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.viewChoice === mode)));
    // A drawer from the previous layout must not leave a backdrop over the new one.
    document.querySelector('#app > aside')?.classList.remove('open');
    document.querySelector('#navBackdrop')?.classList.remove('show');
    document.querySelector('#menu')?.setAttribute('aria-expanded', 'false');
  }
  function close(restoreFocus = false) {
    const panel = document.querySelector('#viewModePanel');
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    document.querySelector('#viewModeButton').setAttribute('aria-expanded', 'false');
    if (restoreFocus) document.querySelector('#viewModeButton').focus();
  }
  apply();
  addEventListener('resize', apply);
  addEventListener('storage', event => {
    if (event.key !== key && event.key !== null) return;
    mode = modes.includes(event.newValue) ? event.newValue : 'auto'; apply();
  });
  addEventListener('DOMContentLoaded', () => {
    apply();
    const trigger = document.querySelector('#viewModeButton'), panel = document.querySelector('#viewModePanel');
    trigger.onclick = () => {
      panel.hidden = !panel.hidden; trigger.setAttribute('aria-expanded', String(!panel.hidden));
      if (!panel.hidden) panel.querySelector('[aria-pressed=true]').focus();
    };
    panel.addEventListener('click', event => {
      const button = event.target.closest('[data-view-choice]'); if (!button) return;
      mode = button.dataset.viewChoice;
      try { localStorage.setItem(key, mode); } catch {}
      apply(); close(true);
    });
    panel.addEventListener('keydown', event => {
      if (!['ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
      const buttons = [...panel.querySelectorAll('[data-view-choice]')];
      let index = buttons.indexOf(document.activeElement);
      index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
      event.preventDefault(); buttons[index].focus();
    });
    document.addEventListener('click', event => { if (!event.target.closest('.view-switch')) close(); });
    document.addEventListener('focusin', event => { if (!event.target.closest('.view-switch')) close(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && !panel.hidden) {event.preventDefault();event.stopImmediatePropagation();close(true);} }, true);
    document.querySelectorAll('#app > aside nav a').forEach(link => {
      link.title = link.textContent.trim(); link.setAttribute('role','button'); link.tabIndex = 0;
      link.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') {event.preventDefault();link.click();} });
    });
  });
})();

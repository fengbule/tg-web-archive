(function () {
  'use strict';
  const system = matchMedia('(prefers-color-scheme: light)');
  let saved;
  try { saved = localStorage.getItem('nebula-theme'); } catch {}
  const apply = theme => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'light' ? '#f5f7fb' : '#101216');
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      button.setAttribute('aria-label', theme === 'dark' ? '切换浅色主题' : '切换深色主题');
      button.setAttribute('aria-pressed', String(theme === 'light'));
      button.title = button.getAttribute('aria-label');
      button.innerHTML = theme === 'dark'
        ? '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/></svg>'
        : '<svg viewBox="0 0 24 24"><path d="M20.5 14A8.7 8.7 0 0 1 10 3.5 8.8 8.8 0 1 0 20.5 14Z"/></svg>';
    });
  };
  window.toggleTheme = () => {
    saved = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    try { localStorage.setItem('nebula-theme', saved); } catch {}
    apply(saved);
  };
  apply(saved === 'light' || saved === 'dark' ? saved : system.matches ? 'light' : 'dark');
  system.addEventListener('change', () => { if (!saved) apply(system.matches ? 'light' : 'dark'); });
  addEventListener('storage', event => {
    if (event.key !== 'nebula-theme') return;
    saved = event.newValue;
    apply(saved === 'light' || saved === 'dark' ? saved : system.matches ? 'light' : 'dark');
  });
  document.addEventListener('DOMContentLoaded', () => apply(document.documentElement.dataset.theme));
})();

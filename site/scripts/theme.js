(() => {
  const root = document.documentElement;
  const themeMeta = document.querySelector('meta[name="theme-color"]');
  const stored = (() => {
    try { return localStorage.getItem('sonara-site-theme'); } catch { return null; }
  })();
  const initial = stored === 'light' || stored === 'dark'
    ? stored
    : (window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark');

  function applyTheme(theme) {
    root.dataset.theme = theme;
    themeMeta?.setAttribute('content', theme === 'light' ? '#f4f7f2' : '#101010');
    document.querySelectorAll('[data-theme-src-light][data-theme-src-dark]').forEach((image) => {
      const source = theme === 'light' ? image.dataset.themeSrcLight : image.dataset.themeSrcDark;
      if (source && image.getAttribute('src') !== source) image.setAttribute('src', source);
    });
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      const next = theme === 'dark' ? 'light' : 'dark';
      button.setAttribute('aria-pressed', String(theme === 'light'));
      button.setAttribute('aria-label', `Switch to ${next} theme`);
      button.setAttribute('title', `Switch to ${next} theme`);
    });
  }

  applyTheme(initial);
  document.addEventListener('DOMContentLoaded', () => applyTheme(root.dataset.theme), { once: true });
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-theme-toggle]');
    if (!button) return;
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem('sonara-site-theme', next); } catch { /* Storage can be unavailable in private contexts. */ }
  });
})();

(() => {
  const toggle = document.querySelector('.menu-toggle');
  const navigation = document.querySelector('#primary-navigation');

  if (toggle && navigation) {
    const closeMenu = (restoreFocus = false) => {
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', 'Open navigation');
      navigation.classList.remove('is-open');
      if (restoreFocus) toggle.focus();
    };

    toggle.addEventListener('click', () => {
      const open = toggle.getAttribute('aria-expanded') !== 'true';
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
      navigation.classList.toggle('is-open', open);
      if (open) navigation.querySelector('a')?.focus();
    });

    navigation.addEventListener('click', (event) => {
      if (event.target.closest('a')) closeMenu();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') closeMenu(true);
    });
    window.addEventListener('resize', () => {
      if (window.innerWidth > 700) closeMenu();
    });
  }

  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const panels = tabs.map((tab) => document.getElementById(tab.getAttribute('aria-controls'))).filter(Boolean);
  const activateTab = (tab, moveFocus = false) => {
    tabs.forEach((item) => {
      const active = item === tab;
      item.setAttribute('aria-selected', String(active));
      item.tabIndex = active ? 0 : -1;
    });
    panels.forEach((panel) => { panel.hidden = panel.id !== tab.getAttribute('aria-controls'); });
    if (moveFocus) tab.focus();
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateTab(tab));
    tab.addEventListener('keydown', (event) => {
      let nextIndex;
      if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') nextIndex = 0;
      else if (event.key === 'End') nextIndex = tabs.length - 1;
      else return;
      event.preventDefault();
      activateTab(tabs[nextIndex], true);
    });
  });
})();

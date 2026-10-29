import { detectDevice, LATEST_RELEASE_URL, REPOSITORY, selectReleaseAsset } from './downloads.mjs';

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

  const platformSelect = document.querySelector('#download-platform');
  const architectureSelect = document.querySelector('#download-arch');
  const downloadButton = document.querySelector('#download-button');
  const downloadStatus = document.querySelector('#download-status');
  const downloadMeta = document.querySelector('#download-meta');
  const latestReleaseLink = document.querySelector('#latest-release-link');

  if (platformSelect && architectureSelect && downloadButton && downloadStatus && downloadMeta) {
    const state = { release: null, error: '', device: { platform: '', architecture: '' } };
    latestReleaseLink?.setAttribute('href', LATEST_RELEASE_URL);

    const formatBytes = (bytes) => {
      if (!Number.isFinite(bytes) || bytes <= 0) return '';
      const units = ['B', 'KB', 'MB', 'GB'];
      let value = bytes;
      let unit = 0;
      while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
      }
      return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
    };

    const updateSelection = () => {
      if (state.error) {
        downloadStatus.textContent = state.error;
        downloadMeta.textContent = 'You can still open the GitHub releases page to check availability.';
        downloadButton.href = LATEST_RELEASE_URL;
        downloadButton.textContent = 'Browse releases ↗';
        return;
      }
      const platform = platformSelect.value;
      const architecture = architectureSelect.value === 'auto'
        ? (platform === state.device.platform ? state.device.architecture : '')
        : architectureSelect.value;
      const asset = selectReleaseAsset(state.release, platform, architecture);
      if (asset) {
        downloadButton.href = asset.browser_download_url;
        downloadButton.textContent = `Download for ${platformSelect.selectedOptions[0].text} `;
        const arrow = document.createElement('span');
        arrow.setAttribute('aria-hidden', 'true');
        arrow.textContent = '↓';
        downloadButton.append(arrow);
        downloadStatus.textContent = `Sonara ${state.release.tag_name} · ${platformSelect.selectedOptions[0].text} · ${architecture}`;
        downloadMeta.textContent = `${asset.name}${asset.size ? ` · ${formatBytes(asset.size)}` : ''}`;
        return;
      }

      downloadButton.href = state.release?.html_url || LATEST_RELEASE_URL;
      downloadButton.textContent = state.release ? 'View release assets ↗' : 'Browse releases ↗';
      if (!platform) {
        downloadStatus.textContent = state.release ? `Sonara ${state.release.tag_name} is available. Choose a platform.` : 'Choose your platform to find an installer.';
      } else if (!architecture) {
        downloadStatus.textContent = 'Choose an architecture to find the matching installer.';
      } else {
        downloadStatus.textContent = `No installer is published for ${platformSelect.selectedOptions[0].text} · ${architecture}.`;
      }
      downloadMeta.textContent = state.release ? `Latest release: ${state.release.tag_name}.` : 'Installer details will appear here.';
    };

    platformSelect.addEventListener('change', () => {
      architectureSelect.value = 'auto';
      updateSelection();
    });
    architectureSelect.addEventListener('change', updateSelection);

    Promise.all([
      detectDevice().then((device) => {
        state.device = device;
        if (device.platform) platformSelect.value = device.platform;
        if (device.architecture) architectureSelect.value = device.architecture;
      }),
      fetch(`https://api.github.com/repos/${REPOSITORY}/releases/latest`, {
        headers: { Accept: 'application/vnd.github+json' },
      }).then((response) => {
        if (!response.ok) throw new Error(response.status === 404 ? 'No published release is available yet.' : `Release lookup failed (${response.status}).`);
        return response.json();
      }).then((release) => {
        state.release = release;
        if (release.html_url) latestReleaseLink?.setAttribute('href', release.html_url);
      }),
    ]).catch((error) => {
      state.error = error.message || 'Could not load release information.';
    }).finally(updateSelection);
  }
})();

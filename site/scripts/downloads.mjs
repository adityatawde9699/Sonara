export const REPOSITORY = 'adityatawde9699/Sonara';
export const LATEST_RELEASE_URL = `https://github.com/${REPOSITORY}/releases/latest`;

const ASSET_BY_TARGET = {
  'windows/x86_64': 'Sonara-windows-x86_64-setup.exe',
  'linux/x86_64': 'Sonara-linux-x86_64.AppImage',
  'macos/aarch64': 'Sonara-macos-aarch64.dmg',
  'macos/x86_64': 'Sonara-macos-x86_64.dmg',
};

export function normalizePlatform(value = '') {
  const platform = String(value).toLowerCase();
  if (/windows|win32|win64/.test(platform)) return 'windows';
  if (/mac|darwin/.test(platform)) return 'macos';
  if (/linux|x11/.test(platform)) return 'linux';
  return '';
}

export function normalizeArchitecture(architecture = '', bitness = '') {
  const cpu = String(architecture).toLowerCase();
  const width = String(bitness).toLowerCase();
  if (/aarch64|arm64/.test(cpu) || (/^arm/.test(cpu) && (width === '64' || cpu.includes('64')))) return 'aarch64';
  if (/x86_64|x86-64|amd64|x64/.test(cpu) || (cpu === 'x86' && width === '64')) return 'x86_64';
  return '';
}

export async function detectDevice(navigatorLike = globalThis.navigator) {
  const hints = navigatorLike?.userAgentData;
  let architecture = '';
  let bitness = '';
  if (hints?.getHighEntropyValues) {
    try {
      const values = await hints.getHighEntropyValues(['architecture', 'bitness']);
      architecture = values.architecture || '';
      bitness = values.bitness || '';
    } catch {
      // Keep platform detection available if the browser declines high-entropy hints.
    }
  }
  return {
    platform: normalizePlatform(hints?.platform || navigatorLike?.platform || navigatorLike?.userAgent),
    architecture: normalizeArchitecture(architecture, bitness),
  };
}

export function selectReleaseAsset(release, platform, architecture) {
  const name = ASSET_BY_TARGET[`${platform}/${architecture}`];
  if (!name || !Array.isArray(release?.assets)) return null;
  return release.assets.find((asset) => asset.name === name) || null;
}

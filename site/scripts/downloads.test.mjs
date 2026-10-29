import test from 'node:test';
import assert from 'node:assert/strict';
import {
  detectDevice,
  normalizeArchitecture,
  normalizePlatform,
  selectReleaseAsset,
} from './downloads.mjs';

test('normalizes common operating system names', () => {
  assert.equal(normalizePlatform('Win32'), 'windows');
  assert.equal(normalizePlatform('MacIntel'), 'macos');
  assert.equal(normalizePlatform('Linux x86_64'), 'linux');
  assert.equal(normalizePlatform('FreeBSD'), '');
});

test('normalizes architecture hints without guessing unknown devices', () => {
  assert.equal(normalizeArchitecture('arm', '64'), 'aarch64');
  assert.equal(normalizeArchitecture('x86', '64'), 'x86_64');
  assert.equal(normalizeArchitecture('x86', '32'), '');
});

test('uses client hints to detect platform and architecture', async () => {
  const device = await detectDevice({
    platform: 'MacIntel',
    userAgentData: {
      platform: 'macOS',
      getHighEntropyValues: async () => ({ architecture: 'arm', bitness: '64' }),
    },
  });
  assert.deepEqual(device, { platform: 'macos', architecture: 'aarch64' });
});

test('maps only published installers to a selected platform and architecture', () => {
  const release = { assets: [{ name: 'Sonara-macos-aarch64.dmg', browser_download_url: 'https://example.test/sonara.dmg' }] };
  assert.equal(selectReleaseAsset(release, 'macos', 'aarch64'), release.assets[0]);
  assert.equal(selectReleaseAsset(release, 'macos', 'x86_64'), null);
});

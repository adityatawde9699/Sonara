#!/usr/bin/env bash
set -euo pipefail

security delete-keychain "$RUNNER_TEMP/sonara-signing.keychain-db" >/dev/null 2>&1 || true
if [[ -s "$RUNNER_TEMP/sonara-default-keychain" ]]; then
  security default-keychain -d user -s "$(cat "$RUNNER_TEMP/sonara-default-keychain")"
fi
rm -f "$RUNNER_TEMP/sonara-signing-certificate.p12"
rm -f "$RUNNER_TEMP/sonara-default-keychain"

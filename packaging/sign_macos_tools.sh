#!/usr/bin/env bash
set -euo pipefail

tools="${1:?Usage: sign_macos_tools.sh <tools-directory>}"
if [[ -z "${APPLE_CERTIFICATE:-}" || -z "${APPLE_CERTIFICATE_PASSWORD:-}" || -z "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  echo "Apple signing credentials are unavailable; staged tools will remain unsigned and the install smoke check will fail." >&2
  exit 0
fi

keychain="$RUNNER_TEMP/sonara-signing.keychain-db"
certificate="$RUNNER_TEMP/sonara-signing-certificate.p12"
security default-keychain -d user | tr -d '"' > "$RUNNER_TEMP/sonara-default-keychain"
keychain_password="$(openssl rand -hex 24)"

printf '%s' "$APPLE_CERTIFICATE" | base64 --decode > "$certificate"
security create-keychain -p "$keychain_password" "$keychain"
security set-keychain-settings -lut 21600 "$keychain"
security unlock-keychain -p "$keychain_password" "$keychain"
security default-keychain -d user -s "$keychain"
security import "$certificate" -k "$keychain" -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$keychain_password" "$keychain"
security list-keychains -d user -s "$keychain"

sign_file() {
  local file="$1"
  local identifier="com.sonara.bundled.$(basename "$file" | tr -c '[:alnum:].-' '-')"
  codesign --force --options runtime --timestamp --sign "$APPLE_SIGNING_IDENTITY" --identifier "$identifier" "$file"
  codesign --verify --strict --verbose=2 "$file"
}

while IFS= read -r -d '' library; do
  sign_file "$library"
done < <(find "$tools/lib" -type f -name '*.dylib' -print0 | sort -z)

while IFS= read -r -d '' executable; do
  if file "$executable" | grep -q 'Mach-O'; then sign_file "$executable"; fi
done < <(find "$tools/bin" -type f -print0 | sort -z)

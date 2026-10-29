# Release process

## Automated tagged builds

Pushing a tag matching `vMAJOR.MINOR.PATCH` starts `.github/workflows/package.yml`. The tag must match both `src-tauri/Cargo.toml` and `src-tauri/tauri.conf.json`; update those version fields together before tagging. The workflow can also be run manually with a release tag and platform selection to retry packaging from the current branch and attach installers to an existing release without moving its tag. A platform-specific run publishes only that platform's installer assets; run `all` for the complete matrix.

The workflow first runs Python, React, site-selector, Rust, and release metadata checks. Native jobs stage Poppler/Tesseract, build Windows x86_64 NSIS, Linux x86_64 `.deb` and AppImage, macOS Apple Silicon `.dmg`, and macOS Intel `.dmg` packages, then upload stable filenames. Separate hosted runners install each package, exercise bundled PDF extraction/OCR and runtime discovery, and check data retention. Windows and macOS checks also verify signatures and notarization. Publication waits for every smoke check and requires platform signing credentials.

The marketing site reads the latest published GitHub Release and matches its assets by those stable filenames. A release only becomes downloadable there after publication.

## Creating a release

1. Update the version in `src-tauri/Cargo.toml` and `src-tauri/tauri.conf.json` to the same stable version.
2. Update `CHANGELOG.md` and review the runtime, dependency, and licensing notes.
3. Run Python, frontend, and Rust checks locally. Check the Pages download selector with `node --test site/scripts/downloads.test.mjs`.
4. Commit and push the changes, then create and push the matching annotated tag, for example `v0.2.0`.
5. Wait for the complete **Build and publish desktop releases** workflow. Review all installer files and checksums on the created release and confirm the site reflects the release.

Do not delete or replace an existing release tag to retry a failed build. Correct the underlying failure and use a new version tag after review.

## Signing, notarization, and release gate

Add these GitHub Actions repository secrets before pushing a release tag:

- `SONARA_WINDOWS_PFX_BASE64`: base64 encoded Windows Authenticode PFX certificate.
- `SONARA_WINDOWS_PFX_PASSWORD`: PFX password.
- `APPLE_CERTIFICATE`: base64 encoded Developer ID Application certificate in `.p12` format.
- `APPLE_CERTIFICATE_PASSWORD`: `.p12` password.
- `APPLE_SIGNING_IDENTITY`: Developer ID Application identity name.
- `APPLE_ID`, `APPLE_PASSWORD`, and `APPLE_TEAM_ID`: Apple notarization credentials (use an app-specific password).

The Windows job signs the frozen Python runtime and staged native tools, and Tauri signs the app and NSIS installer. Tauri signs and notarizes the macOS app and disk image. The release job refuses publication if any required secret is absent. No signed/notarized release or successful clean-runner execution has been observed yet.

Windows Poppler and Tesseract downloads are pinned and hash-checked. The pinned Tesseract installer is 5.5.3, while upstream 5.5.4 (released 2026-10-28) fixes security advisories. Update and validate this dependency before publishing Windows installers. License inventory and SBOM generation also remain outstanding.

## Supported artifact matrix and limitations

The current workflow targets Windows x86_64, Linux x86_64, macOS aarch64, and macOS x86_64. It does not currently build Windows ARM64 or Linux ARM64. Hosted runner install checks are configured but must pass on CI; they do not replace tests on fresh end-user VMs.

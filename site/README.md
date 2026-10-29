# Sonara website

This directory contains Sonara's independent, static marketing website. It uses plain HTML, CSS, JavaScript, and static SVG/WebP assets. It does not import the desktop application's React or Tauri code and does not add dependencies to its package manifests.

## Preview locally

From the repository root, run:

```sh
python3 -m http.server 4173 --directory site
```

Then open <http://localhost:4173>. Stop the preview with `Ctrl+C`.

Opening `index.html` directly also works for basic review, but an HTTP server is closer to a static-hosting environment.

## Build and deployment

There is no build step. The website does not need the desktop runtime, backend, database, authentication, or environment variables.

### GitHub Pages

GitHub's [branch-based Pages source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) only offers the repository root or `/docs`, so `site/` will not appear in that folder picker. This repository includes [a Pages workflow](../.github/workflows/pages.yml) that uploads the `site/` directory as the Pages artifact.

1. Push the workflow and website files to the `master` branch.
2. In GitHub, open **Settings → Pages** and set **Build and deployment → Source** to **GitHub Actions**. Do not select “Deploy from a branch.”
3. The workflow deploys after a push that changes `site/`. You can also run **Deploy Sonara website to GitHub Pages** manually from the Actions tab while on `master`.
4. GitHub displays the published URL in the workflow run and Pages settings. No custom domain is assumed.

The Pages workflow only publishes `site/`; it does not copy website assets into the desktop application or alter its build.

## Download selector and product links

The download selector reads the latest published release from GitHub's public Releases API, detects the visitor's platform and architecture where browser client hints allow, and lets visitors override either choice. Installer asset names are shared with `packaging/prepare_release_assets.py`; update both if the release naming scheme changes. The Latest GitHub Release link remains available when the API is unavailable or the selected build does not exist. No release is shown as downloadable until GitHub publishes one.

The repository, documentation, and [GPL-3.0-only license](../LICENSE) links in `index.html` point to `https://github.com/adityatawde9699/Sonara`. Keep navigation destinations anchored to sections that exist.

Before changing a product claim, verify it against the desktop implementation and project documentation. In particular, engine and voice availability depends on local runtimes and model files; optional assistant providers are configured separately and may be remote. Keep authentic screenshots labeled as captures and illustrative UI fragments labeled as examples.

## Assets

- `assets/sonara-mark.svg` is the inline-independent brand mark used in the page.
- `assets/favicon.svg` is the browser icon.
- `assets/og-card.svg` is the social preview illustration.
- `assets/images/sonara-home.webp` and `assets/images/sonara-home-light.webp` are optimized dark and light captures used by the hero when the site theme changes. Their original PNGs are retained in the repository.

Replace or add optimized assets under `assets/`. Update the relative references in `index.html` and preserve image dimensions (or specify `width` and `height`) to avoid layout shifts. The home screenshot is an authentic application capture; the additional reader and workflow fragments are illustrative website visuals, not screenshots.

## Theme and interactions

The site has no runtime package dependencies. Theme preference is stored in browser `localStorage` when available and otherwise follows the system preference. The mobile navigation, spoken-text sample tabs, and release download selector are implemented in `scripts/main.js`; platform and asset mapping helpers are in `scripts/downloads.mjs`. Run the helper tests with `node --test site/scripts/downloads.test.mjs`. Theme behavior is in `scripts/theme.js`.

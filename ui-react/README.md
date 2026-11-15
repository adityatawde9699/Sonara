# Sonara desktop frontend

The React 19 + TypeScript interface for the Sonara Tauri app. It runs inside the Tauri WebView and talks to the Rust backend only through typed `invoke` commands in `src/lib/tauri.ts`; it has no filesystem or shell access of its own.

## Layout

- `src/App.tsx`: page routing (home, library, reader, about) and app-level state.
- `src/hooks/useSonara.ts`: the reading session, the audio player, and global keyboard shortcuts.
- `src/hooks/useModalDialog.ts`: shared dialog behaviour (focus trap, focus restore, topmost-only Escape).
- `src/components/`: the player, reader, assistant, settings, history, and shortcuts UI, each with a `*.test.tsx` beside it.
- `src/lib/`: the Tauri command wrapper and local history storage.

## Commands

```sh
npm ci            # install exact locked dependencies
npm run dev       # Vite dev server on port 1420 (browser preview; desktop commands are disabled)
npm test          # Vitest
npm run lint      # oxlint
npm run build     # type-check and production build into dist/, which Tauri bundles
```

To run the full desktop app, see [Development setup](../docs/DEVELOPMENT.md).

# Sonara desktop frontend

The React 19 + TypeScript interface for the Sonara Tauri app. It runs inside the Tauri WebView and talks to the Rust backend only through typed `invoke` commands in `src/lib/tauri.ts`; it has no filesystem or shell access of its own.

## Layout

- `src/App.tsx`: page routing (home, library, reader, about) and app-level state.
- `src/hooks/useSonara.ts`: the document phase, synthesis events, library, dialogs, and global keyboard shortcuts. It composes:
  - `src/hooks/useAudioPlayer.ts`: passage-by-passage playback, pauses between passages, seeking, speed, retry/skip, and progress saving.
  - `src/hooks/useSpeechSettings.ts`: engine, voice, variation, and narration options, persisted per device.
- `src/hooks/useModalDialog.ts`: shared dialog behaviour (focus trap, focus restore, topmost-only Escape).
- `src/components/`: the player, reader, assistant, settings, history, and shortcuts UI, each with a `*.test.tsx` beside it.
- `src/lib/`: the typed Tauri command wrapper. The library itself is kept by the backend.

## Commands

```sh
npm ci            # install exact locked dependencies
npm run dev       # Vite dev server on port 1420 (browser preview; desktop commands are disabled)
npm test          # Vitest
npm run lint      # oxlint
npm run build     # type-check and production build into dist/, which Tauri bundles
```

To run the full desktop app, see [Development setup](../docs/DEVELOPMENT.md).

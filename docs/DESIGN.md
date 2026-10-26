# Sonara interface design

## Visual direction

Sonara uses a quiet editorial workspace: mineral off-white surfaces, deep green-black text, and a single muted teal for active listening and primary actions. The design makes the current document and its playback controls the first thing a returning reader sees. The empty state makes PDF import the clear first action. It avoids decorative charts, fake waveforms, gradients, and text/audio synchronization claims the current session API cannot support.

Taste Skill's `editorial-greeting` app direction informed the home screen. Its greeting and tonal panel approach was adapted for a long listening session: the active playback surface is the main object, and recent listening is secondary. The app has no meaningful aggregate metrics, so the design does not invent any.

## Figma

[Sonara — Local Listening Workspace](https://www.figma.com/design/OykNZUJvbXKQcMbwSO1Nqb)

The Figma file contains local color variables, a typography ramp, a home example state, and a listening-workspace example state. The example document names and playback values are illustrative design content. In the running application, session metadata and playback progress come from the local Tauri session and persisted progress.

## Foundations

| Token | Light | Dark |
| --- | --- | --- |
| Canvas | `#F4F7F2` | `#171B18` |
| Surface | `#FBFCF9` | `#1D231F` |
| Raised surface | `#FFFFFF` | `#242B26` |
| Main text | `#232823` | `#EDF2ED` |
| Secondary text | `#636D63` | `#A7B2A8` |
| Divider | `#DDE3DC` | `#343D36` |
| Accent | `#39776D` | `#8BC0B1` |

Typography uses the system sans stack with a restrained display scale. The app does not fetch fonts from the network, so it remains visually usable offline. Spacing uses a 4/8px rhythm, panels use modest 8–14px corners, and playback time uses tabular numerals. Focus rings, pressed states, reduced-motion support, and a system dark theme are included.

## Current screen map

- **Listening home:** current restored session and actual player controls, multi-format document preparation, recent listening history, and an on-device processing note.
- **Reading view:** locally extracted text for the active desktop session, with in-document search, paragraph paging, and adjustable type size. It explicitly states that audio position is not synchronized with paragraphs.
- **History:** existing drawer backed by local browser metadata. It lists previously prepared files and can clear that metadata.
- **Settings:** existing voice selector, playback presets, audio pipeline details, and optional assistant configuration.
- **Shortcuts:** existing keyboard reference modal.
- **Assistant:** existing document assistant flow, which depends on user configuration and may use a remote provider.

The reader view calls the existing Rust `get_document_text` command for the active session. The backend returns extracted local text, but does not provide stable page/heading structure or text-to-audio timing. The UI therefore paginates extracted paragraphs, does not claim original page layout, and does not claim sentence highlighting or synchronized reading position.

## Product facts reflected in the interface

- The Tauri picker and backend accept PDF, TXT/TEXT, Markdown, DOCX, and EPUB files. Scanned PDFs use the existing optional local OCR path when it is installed.
- Piper voices are discovered from installed local voice models. The selector does not offer uninstalled voices.
- Playback supports play, pause, seeking, passage selection, retry/skip on audio errors, and a 0.7×–1.5× rate.
- The desktop session and saved playback position are restored through Rust commands.
- The visible recent list comes from local browser storage and contains metadata, not source paths. Recent rows are informational; they do not promise that an older source file can be reopened.
- Recent file badges are derived from each stored filename. The picker filters for all supported document formats, with an all-files option for system compatibility.
- Document synthesis, generated audio, and playback are local. The optional assistant can be configured separately and is not implied to be local by the privacy note.

## Reusable UI

The implementation reuses the existing `TopBar`, `DocumentCard`, `PlayerCard`, settings/history/assistant dialogs, and adds the app rail, recent listening rows, privacy note, responsive workspace composition, and `ReaderPanel`. The document actions now wrap as a group at narrow widths, and the passage navigator is labeled and reflects generated audio chunks instead of reading as decorative dots. CSS variables live in `ui-react/src/index.css`; reading text uses the existing typed Tauri IPC command.

## Known gaps

- No library database or source-file index exists; the current list is recent metadata only.
- No durable library database or source-file index exists. Reading text is available only for the current backend session; old recent-history entries cannot restore their text.
- The backend does not expose headings, original page mapping, or audio text timing, so outline navigation and synchronized text/audio highlighting are unavailable.
- Drag-and-drop, import-stage progress before synthesis, and cancellation of the native picker are not implemented.
- Model download/management and pronunciation controls are not implemented in the desktop UI.
- The existing design is a polished prototype, not a claim of production readiness. Desktop interaction still needs validation in a graphical Tauri/WebView session.

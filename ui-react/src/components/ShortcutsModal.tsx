import { type FC } from "react";
import { useModalDialog } from "../hooks/useModalDialog";
import { X } from "lucide-react";

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

const SHORTCUTS = [
  { key: "Space / K", description: "Play or pause narration" },
  { key: "← / J", description: "Rewind 5 seconds" },
  { key: "→ / L", description: "Skip forward 5 seconds" },
  { key: "↑ / ]", description: "Increase listening speed (+0.1×)" },
  { key: "↓ / [", description: "Decrease listening speed (-0.1×)" },
  { key: "Home", description: "Jump to beginning of document" },
  { key: "End", description: "Jump to end of document" },
  { key: "A", description: "Open or close the document assistant" },
  { key: "Ctrl / ⌘ + K", description: "Search your library" },
  { key: "?", description: "Open this keyboard shortcuts cheatsheet" },
  { key: "Esc", description: "Close the open dialog" },
];

export const ShortcutsModal: FC<Props> = ({ isOpen, onClose }) => {
  const dialogRef = useModalDialog<HTMLDivElement>(isOpen, onClose);

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div className="modal-title-wrap">
            <h2 id="shortcuts-title">Keyboard shortcuts</h2>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Close shortcuts dialog"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <p className="modal-desc">
          Navigate your document quickly without touching the mouse.
        </p>

        <div className="shortcuts-list">
          {SHORTCUTS.map((s) => (
            <div key={s.key} className="shortcut-item">
              <span className="shortcut-desc">{s.description}</span>
              <kbd className="shortcut-kbd">{s.key}</kbd>
            </div>
          ))}
        </div>

        <div className="modal-footer">
          <button type="button" className="button button-secondary" onClick={onClose}>
            Got it
          </button>
        </div>
      </div>
    </div>
  );
};

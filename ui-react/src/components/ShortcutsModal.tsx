import { type FC, useEffect } from "react";

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
  { key: "?", description: "Toggle this keyboard shortcuts cheatsheet" },
  { key: "Esc", description: "Close dialogs" },
];

export const ShortcutsModal: FC<Props> = ({ isOpen, onClose }) => {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div className="modal-title-wrap">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect x="2" y="4" width="20" height="16" rx="2" />
              <line x1="6" y1="8" x2="6" y2="8" />
              <line x1="10" y1="8" x2="10" y2="8" />
              <line x1="14" y1="8" x2="14" y2="8" />
              <line x1="18" y1="8" x2="18" y2="8" />
              <line x1="6" y1="12" x2="6" y2="12" />
              <line x1="18" y1="12" x2="18" y2="12" />
              <line x1="10" y1="16" x2="14" y2="16" />
            </svg>
            <h2 id="shortcuts-title">Keyboard Shortcuts</h2>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Close shortcuts dialog"
          >
            ✕
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

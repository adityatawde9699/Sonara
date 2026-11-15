import { type FC } from "react";
import { useModalDialog } from "../hooks/useModalDialog";
import type { LibraryDocument } from "../lib/tauri";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  recentDocs: LibraryDocument[];
  onClearHistory: () => void;
  /** Reopen a document; omitted, rows are informational only. */
  onOpenDocument?: (sourceSha256: string) => void;
  /** The document currently loaded in the player. */
  currentSha256?: string;
}

function formatClock(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds || 0));
  const mins = Math.floor(value / 60);
  const secs = value % 60;
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function formatRelativeTime(timestamp: number): string {
  const diff = Date.now() - timestamp;
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export const HistoryDrawer: FC<Props> = ({
  isOpen,
  onClose,
  recentDocs,
  onClearHistory,
  onOpenDocument,
  currentSha256,
}) => {
  const dialogRef = useModalDialog<HTMLDivElement>(isOpen, onClose);

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="modal-card drawer-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="history-title"
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
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
            <h2 id="history-title">Document History</h2>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Close history drawer"
          >
            ✕
          </button>
        </div>

        <p className="modal-desc">
          Recent documents prepared for local listening on this machine.
        </p>

        {recentDocs.length === 0 ? (
          <div className="history-empty">
            <svg
              width="36"
              height="36"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="empty-icon"
              aria-hidden="true"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
            <p>No recent documents yet.</p>
            <span>Open and prepare a document to begin listening.</span>
          </div>
        ) : (
          <div className="history-list">
            {recentDocs.map((doc) => (
              <div key={doc.sourceSha256} className="history-item">
                <div className="history-icon" aria-hidden="true">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                </div>
                <div className="history-meta">
                  <h4 className="history-doc-name" title={doc.sourceName}>
                    {doc.sourceName}
                  </h4>
                  <div className="history-details">
                    <span>{doc.chunksCount} passages</span>
                    <span>·</span>
                    <span>{formatClock(doc.totalDurationSeconds)}</span>
                    <span>·</span>
                    <span>{formatRelativeTime(doc.lastListenedAt)}</span>
                  </div>
                  {!doc.available && (
                    <span className="history-unavailable">File moved or deleted</span>
                  )}
                </div>
                {onOpenDocument && (
                  <button
                    type="button"
                    className="button button-secondary history-open"
                    onClick={() => onOpenDocument(doc.sourceSha256)}
                    disabled={!doc.available && doc.sourceSha256 !== currentSha256}
                    aria-label={`${doc.sourceSha256 === currentSha256 ? "Continue" : "Open"} ${doc.sourceName}`}
                  >
                    {doc.sourceSha256 === currentSha256 ? "Continue" : "Open"}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="modal-footer">
          {recentDocs.length > 0 && (
            <button
              type="button"
              className="text-button text-button-danger"
              onClick={onClearHistory}
            >
              Clear history
            </button>
          )}
          <button type="button" className="button button-secondary" onClick={onClose} style={{ marginLeft: "auto" }}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

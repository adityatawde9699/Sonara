import { type FC } from "react";
import { useModalDialog } from "../hooks/useModalDialog";
import type { LibraryDocument } from "../lib/tauri";
import { FileText, X } from "lucide-react";

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
            <h2 id="history-title">History</h2>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Close history drawer"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <p className="modal-desc">
          Recent documents prepared for local listening on this machine.
        </p>

        {recentDocs.length === 0 ? (
          <div className="history-empty">
            
            <p>No recent documents yet.</p>
            <span>Open and prepare a document to begin listening.</span>
          </div>
        ) : (
          <div className="history-list">
            {recentDocs.map((doc) => (
              <div key={doc.sourceSha256} className="history-item">
                <div className="history-icon" aria-hidden="true">
                  <FileText size={16} aria-hidden="true" />
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

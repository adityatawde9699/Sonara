import { useEffect, type FC } from "react";
import type { NarrationPreview } from "../lib/tauri";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  preview: NarrationPreview | null;
  loading: boolean;
  error: string;
}

export const NarrationPreviewModal: FC<Props> = ({ isOpen, onClose, preview, loading, error }) => {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;
  const changed = preview?.units.reduce((total, unit) => total + unit.changes.length, 0) ?? 0;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section
        className="modal-card narration-preview-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="narration-preview-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="modal-header">
          <div>
            <p className="reader-eyebrow">LOCAL NARRATION PREVIEW</p>
            <h2 id="narration-preview-title">What Sonara will read</h2>
            <p className="settings-section-desc">Your source document remains unchanged. Previewing does not generate audio.</p>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="Close narration preview">×</button>
        </header>
        <div className="narration-preview-body">
          {loading ? (
            <div className="reader-state" role="status"><span className="reader-loader" />Preparing local preview…</div>
          ) : error ? (
            <div className="reader-state reader-error" role="alert"><p>{error}</p></div>
          ) : preview ? (
            <>
              <div className="narration-preview-meta">
                <span>{preview.language.replace("_", "-")}</span>
                <span>{preview.totalUnits.toLocaleString()} speech units</span>
                <span>{changed} spoken-text changes in preview</span>
              </div>
              <ol className="narration-preview-list">
                {preview.units.map((unit) => (
                  <li key={unit.order}>
                    <p className="narration-source-text">{unit.sourceText}</p>
                    <p className="narration-spoken-text">{unit.spokenText}</p>
                    {unit.changes.length > 0 && (
                      <ul className="narration-change-list">
                        {unit.changes.map((change, index) => (
                          <li key={`${change.overrideId}-${index}`}>
                            {change.matchedSourceText} <span aria-hidden="true">→</span> {change.replacement || "omitted"}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ol>
              {preview.units.length < preview.totalUnits && <p className="narration-preview-limit">Showing the first {preview.units.length} of {preview.totalUnits} speech units.</p>}
            </>
          ) : null}
        </div>
        <footer className="modal-footer"><button type="button" className="button button-primary" onClick={onClose}>Done</button></footer>
      </section>
    </div>
  );
};

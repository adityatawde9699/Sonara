import type { FC } from "react";
import type { AppPhase } from "../hooks/useSonara";
import { FileText, FolderOpen, MessageCircle, Play } from "lucide-react";

interface Props {
  phase: AppPhase;
  documentName: string;
  statusText: string;
  errorText: string;
  disabled: boolean;
  selectedVoiceName?: string;
  onOpenSettings?: () => void;
  onOpenAssistant?: () => void;
  onChoose: () => void;
  onStartSynthesis: () => void;
  onCancelSynthesis: () => void;
  onPreview?: () => void;
  isPreviewing?: boolean;
}

export const DocumentCard: FC<Props> = ({
  phase,
  documentName,
  statusText,
  errorText,
  disabled,
  selectedVoiceName,
  onOpenSettings,
  onOpenAssistant,
  onChoose,
  onStartSynthesis,
  onCancelSynthesis,
  onPreview,
  isPreviewing = false,
}) => {
  const showSynthesisButton = phase === "selected";
  // A streaming run is still synthesizing, and can still be cancelled.
  const isSynthesizing = phase === "synthesizing" || phase === "streaming";

  return (
    <section className="document-card" aria-labelledby="document-title">
      <div className="card-heading">
        <div className="document-icon" aria-hidden="true">
          <FileText size={18} aria-hidden="true" />
        </div>
        <div className="document-meta">
          <h2 id="document-title" title={documentName || undefined}>
            {documentName || "No document selected"}
          </h2>
          <p id="document-detail" className={errorText ? "error" : ""}>
            {errorText || statusText}
          </p>
          {selectedVoiceName && phase === "selected" && (
            <div className="card-voice-pill">
              <span className="voice-dot" aria-hidden="true" />
              <span className="voice-label">Voice: <strong>{selectedVoiceName}</strong></span>
              {onOpenSettings && (
                <button
                  type="button"
                  className="voice-change-btn"
                  onClick={onOpenSettings}
                  title="Change voice in Settings"
                >
                  Change
                </button>
              )}
            </div>
          )}
        </div>
        <div className="card-actions">
          {onOpenAssistant && (phase === "selected" || phase === "ready") && (
            <button
              type="button"
              className="button button-secondary assistant-card-btn"
              onClick={onOpenAssistant}
              title="Ask the assistant about this document"
            >
              <MessageCircle size={16} aria-hidden="true" />
              Assistant
            </button>
          )}
          <button
            id="choose-document"
            className="button button-secondary"
            type="button"
            disabled={disabled || isSynthesizing}
            onClick={onChoose}
          >
            <FolderOpen size={16} aria-hidden="true" />
            Choose document
          </button>
          {showSynthesisButton && (
            <>
              {onPreview && (
                <button className="button button-secondary" type="button" onClick={onPreview} disabled={isPreviewing}>
                  {isPreviewing ? "Loading preview…" : "Preview narration"}
                </button>
              )}
              <button
                id="start-synthesis"
                className="button button-primary"
                type="button"
                onClick={onStartSynthesis}
              >
                <Play size={16} fill="currentColor" aria-hidden="true" />
                Prepare speech
              </button>
            </>
          )}
        </div>
      </div>

      {isSynthesizing && (
        <div className="synthesis-area">
          <div className="progress-track" aria-hidden="true">
            <span />
          </div>
          <div className="synthesis-row">
            <span id="synthesis-status">{statusText}</span>
            <button
              id="cancel-synthesis"
              className="text-button"
              type="button"
              onClick={onCancelSynthesis}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
};

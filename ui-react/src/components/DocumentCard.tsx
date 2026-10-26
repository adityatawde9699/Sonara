import type { FC } from "react";
import type { AppPhase } from "../hooks/useSonara";

interface Props {
  phase: AppPhase;
  documentName: string;
  statusText: string;
  errorText: string;
  disabled: boolean;
  selectedVoiceName?: string;
  isPolishEnabled?: boolean;
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
  isPolishEnabled,
  onOpenSettings,
  onOpenAssistant,
  onChoose,
  onStartSynthesis,
  onCancelSynthesis,
  onPreview,
  isPreviewing = false,
}) => {
  const showSynthesisButton = phase === "selected";
  const isSynthesizing = phase === "synthesizing";

  return (
    <section className="document-card" aria-labelledby="document-title">
      <div className="card-heading">
        <div className="document-icon" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
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
          {isPolishEnabled && (
            <div className="card-ai-badge" title="AI Narration Polish can clean extraction artifacts and suggest pronunciations">
              <span className="ai-spark" aria-hidden="true">AI</span>
              <span>AI Polish Active</span>
            </div>
          )}
        </div>
        <div className="card-actions">
          {onOpenAssistant && (phase === "selected" || phase === "ready") && (
            <button
              type="button"
              className="button button-secondary assistant-card-btn"
              onClick={onOpenAssistant}
              title="Ask Document Assistant"
            >
              <span className="assistant-btn-spark" aria-hidden="true">AI</span>
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
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
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
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="5 3 19 12 5 21 5 3" />
                </svg>
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

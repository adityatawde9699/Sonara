import type { FC } from "react";

interface Props {
  historyCount: number;
  onOpenHistory: () => void;
  onOpenSettings: () => void;
  onOpenShortcuts: () => void;
  onOpenAssistant?: () => void;
}

export const TopBar: FC<Props> = ({
  historyCount,
  onOpenHistory,
  onOpenSettings,
  onOpenShortcuts,
  onOpenAssistant,
}) => (
  <header className="topbar">
    <a className="brand" href="#" aria-label="Sonara home">
      <span className="brand-mark" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="12" cy="12" r="2.5" />
          <path d="M4.93 4.93a10 10 0 0 1 14.14 0" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
          <path d="M7.76 7.76a6 6 0 0 1 8.48 0" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
          <path d="M10.59 10.59a2 2 0 0 1 2.82 0" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
      </span>
      <span>Sonara</span>
    </a>

    <div className="topbar-actions">
      {onOpenAssistant && (
        <button
          type="button"
          className="topbar-action-btn assistant-btn"
          onClick={onOpenAssistant}
          aria-label="Open document assistant"
          title="Document Assistant & Summaries"
        >
          <span className="assistant-btn-spark" aria-hidden="true">AI</span>
          <span className="action-btn-text">Assistant</span>
        </button>
      )}

      <button
        type="button"
        className="topbar-action-btn"
        onClick={onOpenHistory}
        aria-label={`Open document history, ${historyCount} recent items`}
        title="Recent documents"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
        <span className="action-btn-text">History</span>
        {historyCount > 0 && <span className="action-badge">{historyCount}</span>}
      </button>

      <button
        type="button"
        className="topbar-action-btn"
        onClick={onOpenSettings}
        aria-label="Open audio specifications and settings"
        title="Settings & Audio Specs"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
        <span className="action-btn-text">Settings</span>
      </button>

      <button
        type="button"
        className="topbar-action-btn"
        onClick={onOpenShortcuts}
        aria-label="Open keyboard shortcuts guide"
        title="Shortcuts (?)"
      >
        <kbd className="topbar-kbd">?</kbd>
      </button>

      <span className="local-badge" title="Document extraction and Piper narration run on this device">
        <span className="local-dot" aria-hidden="true" />
        <span>Core runs here</span>
      </span>
    </div>
  </header>
);

import type { FC } from "react";
import { History, MessageCircle, Search, Settings } from "lucide-react";

interface Props {
  historyCount: number;
  onOpenHistory: () => void;
  onOpenSettings: () => void;
  onOpenShortcuts: () => void;
  onOpenAssistant?: () => void;
  searchValue?: string;
  onSearchChange?: (value: string) => void;
}

export const TopBar: FC<Props> = ({
  historyCount,
  onOpenHistory,
  onOpenSettings,
  onOpenShortcuts,
  onOpenAssistant,
  searchValue = "",
  onSearchChange,
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

    {onSearchChange && <label className="global-search">
      <Search size={16} aria-hidden="true" />
      <input id="global-search-input" type="search" aria-label="Global library search" placeholder="Search your library" value={searchValue} onChange={(event) => onSearchChange(event.target.value)} />
      <kbd>Ctrl K</kbd>
    </label>}

    <div className="topbar-actions">
      {onOpenAssistant && (
        <button
          type="button"
          className="topbar-action-btn assistant-btn"
          onClick={onOpenAssistant}
          aria-label="Open document assistant"
          title="Assistant"
        >
          <MessageCircle size={16} aria-hidden="true" />
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
        <History size={16} aria-hidden="true" />
        <span className="action-btn-text">History</span>
        {historyCount > 0 && <span className="action-badge">{historyCount}</span>}
      </button>

      <button
        type="button"
        className="topbar-action-btn"
        onClick={onOpenSettings}
        aria-label="Open audio specifications and settings"
        title="Settings"
      >
        <Settings size={16} aria-hidden="true" />
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

    </div>
  </header>
);

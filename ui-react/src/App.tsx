import { useEffect, useState } from "react";
import { TopBar } from "./components/TopBar";
import { DocumentCard } from "./components/DocumentCard";
import { PlayerCard } from "./components/PlayerCard";
import { ReaderPanel } from "./components/ReaderPanel";
import { ShortcutsModal } from "./components/ShortcutsModal";
import { SettingsModal } from "./components/SettingsModal";
import { HistoryDrawer } from "./components/HistoryDrawer";
import { AssistantDrawer } from "./components/AssistantDrawer";
import { NarrationPreviewModal } from "./components/NarrationPreviewModal";
import { useSonara } from "./hooks/useSonara";
import { AI_NARRATION_POLISH_STORAGE_KEY, type NarrationPreview } from "./lib/tauri";

function formatDuration(seconds: number): string {
  const totalMinutes = Math.max(0, Math.floor(seconds / 60));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours ? `${hours} hr ${minutes} min` : `${totalMinutes} min`;
}

function formatDocumentType(sourceName: string): string {
  const separator = sourceName.lastIndexOf(".");
  return separator >= 0 && separator < sourceName.length - 1
    ? sourceName.slice(separator + 1, separator + 6).toUpperCase()
    : "FILE";
}

export default function App() {
  const sonara = useSonara();
  const [isPolishEnabled, setIsPolishEnabled] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [narrationPreview, setNarrationPreview] = useState<NarrationPreview | null>(null);

  const openNarrationPreview = async () => {
    setPreviewOpen(true);
    setPreviewLoading(true);
    setPreviewError("");
    setNarrationPreview(null);
    try {
      setNarrationPreview(await sonara.previewCurrentNarration());
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : String(error));
    } finally {
      setPreviewLoading(false);
    }
  };

  useEffect(() => {
    try {
      setIsPolishEnabled(localStorage.getItem(AI_NARRATION_POLISH_STORAGE_KEY) === "true");
    } catch {
      // Storage may be unavailable in restricted WebViews.
    }
  }, [sonara.isSettingsOpen]);

  return (
    <main className="app-layout" data-ui="sonara-app">
      <aside className="app-rail" aria-label="Sonara navigation">
        <a className="rail-brand" href="#home" aria-label="Sonara home">
          <span className="rail-brand-mark" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <path d="M5 10v4M9 7v10M13 4v16M17 8v8M21 10v4" />
            </svg>
          </span>
          <span>Sonara</span>
        </a>

        <nav className="rail-nav" aria-label="Primary">
          <a className="rail-nav-item is-current" href="#home" aria-current="page" title="Listening">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="9" />
              <path d="m10 8 6 4-6 4V8Z" />
            </svg>
            <span>Listen</span>
          </a>
          <button className="rail-nav-item" type="button" aria-label="Listening history" onClick={() => sonara.setIsHistoryOpen(true)} title="Listening history">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" />
            </svg>
            <span>History</span>
          </button>
          <button className="rail-nav-item" type="button" onClick={() => sonara.setIsSettingsOpen(true)} title="Settings">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="3" />
              <path d="m19.4 15 .1.1a2 2 0 1 1-2.8 2.8l-.1-.1a2 2 0 0 0-3.4 1.4v.2a2 2 0 1 1-4 0v-.2A2 2 0 0 0 5.8 17l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a2 2 0 0 0-1.4-3.4h-.2a2 2 0 1 1 0-4h.2A2 2 0 0 0 3 4.2l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a2 2 0 0 0 3.4-1.4v-.2a2 2 0 1 1 4 0V0a2 2 0 0 0 3.4 1.4l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a2 2 0 0 0 1.4 3.4h.2a2 2 0 1 1 0 4h-.2a2 2 0 0 0-1.4 3.4Z" transform="translate(1 2) scale(.92)" />
            </svg>
            <span>Settings</span>
          </button>
        </nav>

        <div className="rail-note">
          <span className="rail-note-mark" aria-hidden="true" />
          <span><strong>On this device</strong><small>Document extraction and Piper audio</small></span>
        </div>
      </aside>

      <div className="app-frame" id="home">
        <TopBar
          historyCount={sonara.recentDocs.length}
          onOpenHistory={() => sonara.setIsHistoryOpen(true)}
          onOpenSettings={() => sonara.setIsSettingsOpen(true)}
          onOpenShortcuts={() => sonara.setIsShortcutsOpen(true)}
          onOpenAssistant={() => sonara.setIsAssistantOpen(true)}
        />

        <div className="workspace-content">
          {!sonara.tauriReady && (
            <aside className="banner-preview" role="note" aria-label="Runtime notice">
              <div className="banner-icon" aria-hidden="true">i</div>
              <div className="banner-text">
                <strong>Browser preview</strong>
                <span>Open Sonara as a desktop app to import a document and generate local Piper narration.</span>
              </div>
            </aside>
          )}

          <header className="intro" aria-labelledby="page-title">
            <h1 id="page-title">{sonara.session ? "Pick up where you left off." : "A quieter way to read."}</h1>
            <p className="subtitle">
              {sonara.session
                ? "Your last listening position is saved on this device."
                : "Choose a document and Sonara will prepare it for listening on this device."}
            </p>
          </header>

          <div className="workspace-grid">
            <section className="workspace-primary" aria-label="Current listening and document import">
              {sonara.session && sonara.phase === "ready" && (
                <PlayerCard
                  session={sonara.session}
                  state={sonara.playerState}
                  voiceLabel={sonara.voices.find((voice) => voice.id === sonara.session?.voice)?.name}
                  audioRef={sonara.audioRef}
                  chunkStarts={sonara.chunkStarts}
                  onPlay={sonara.startPlayback}
                  onPause={sonara.pausePlayback}
                  onSeek={sonara.seekTo}
                  onSeekChunk={sonara.seekToChunk}
                  onSpeedChange={(rate) => sonara.setSpeed(rate)}
                  onRetry={sonara.retryPassage}
                  onSkip={sonara.skipPassage}
                  onLoadedMetadata={sonara.handleLoadedMetadata}
                  onTimeUpdate={sonara.handleTimeUpdate}
                  onError={sonara.handleError}
                  onPlaying={sonara.handlePlaying}
                  onEnded={sonara.handleEnded}
                  onCanPlay={sonara.handleCanPlay}
                  onWaiting={sonara.handleWaiting}
                />
              )}

              {sonara.session && sonara.phase === "ready" && (
                <ReaderPanel
                  sourceName={sonara.session.sourceName}
                  sourceSha256={sonara.session.sourceSha256}
                />
              )}

              <section className="import-section" aria-labelledby="import-heading">
                <div className="section-heading">
                  <div>
                    <h2 id="import-heading">{sonara.session ? "Start another listen" : "Start with a document"}</h2>
                    <p>Choose a PDF, text, Markdown, Word, or EPUB file. Extraction and speech generation stay local.</p>
                  </div>
                  <span className="format-mark">PDF · TXT/TEXT · MD · DOCX · EPUB</span>
                </div>
                <DocumentCard
                  phase={sonara.phase}
                  documentName={sonara.documentName}
                  statusText={sonara.statusText}
                  errorText={sonara.errorText}
                  disabled={!sonara.tauriReady}
                  selectedVoiceName={sonara.selectedVoiceName}
                  isPolishEnabled={isPolishEnabled}
                  onOpenSettings={() => sonara.setIsSettingsOpen(true)}
                  onOpenAssistant={() => sonara.setIsAssistantOpen(true)}
                  onChoose={sonara.chooseDocument}
                  onStartSynthesis={sonara.beginSynthesis}
                  onCancelSynthesis={sonara.cancelSynthesis}
                  onPreview={openNarrationPreview}
                  isPreviewing={previewLoading}
                />
              </section>
            </section>

            <aside className="workspace-aside" aria-label="Recent listening">
              <section className="recent-panel" aria-labelledby="recent-title">
                <div className="section-heading recent-heading">
                  <div>
                    <h2 id="recent-title">Recent listening</h2>
                    <p>{sonara.recentDocs.length ? "Prepared documents on this device" : "Your prepared documents will appear here"}</p>
                  </div>
                  {sonara.recentDocs.length > 0 && (
                    <button className="quiet-action" type="button" onClick={() => sonara.setIsHistoryOpen(true)}>
                      View history
                    </button>
                  )}
                </div>
                {sonara.recentDocs.length > 0 ? (
                  <ul className="recent-list">
                    {sonara.recentDocs.slice(0, 5).map((doc) => (
                      <li className="recent-row" key={doc.sourceSha256}>
                        <span className="recent-file-mark" aria-hidden="true">{formatDocumentType(doc.sourceName)}</span>
                        <span className="recent-copy">
                          <strong title={doc.sourceName}>{doc.sourceName}</strong>
                          <small>{doc.chunksCount} passages <span aria-hidden="true">·</span> {formatDuration(doc.totalDurationSeconds)}</small>
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="recent-empty">
                    <p>Nothing prepared yet.</p>
                    <span>Choose a document to create your first listen.</span>
                  </div>
                )}
              </section>

              <div className="privacy-note">
                <span className="privacy-icon" aria-hidden="true">
                  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z" />
                    <path d="m9 12 2 2 4-4" />
                  </svg>
                </span>
                <span><strong>Private by default</strong><small>Document extraction and Piper narration run on this device. Assistant providers are separate.</small></span>
              </div>
            </aside>
          </div>

          <footer className="app-footer">
            <span>Made for focused listening.</span>
            <span>Sonara · Core listening stays local</span>
          </footer>
        </div>
      </div>

      <ShortcutsModal
        isOpen={sonara.isShortcutsOpen}
        onClose={() => sonara.setIsShortcutsOpen(false)}
      />

      <SettingsModal
        isOpen={sonara.isSettingsOpen}
        onClose={() => sonara.setIsSettingsOpen(false)}
        session={sonara.session}
        playbackRate={sonara.playerState.playbackRate}
        onSpeedChange={(speed) => sonara.setSpeed(speed)}
        voices={sonara.voices}
        selectedVoice={sonara.selectedVoice}
        onVoiceChange={(voiceId) => sonara.setSelectedVoice(voiceId)}
        speechEngine={sonara.speechEngine}
        onSpeechEngineChange={sonara.setSpeechEngine}
        resourceProfile={sonara.resourceProfile}
        onResourceProfileChange={sonara.setResourceProfile}
        piperVariation={sonara.piperVariation}
        onVariationChange={sonara.setPiperVariation}
        expandDates={sonara.expandDates}
        onExpandDatesChange={sonara.setExpandDates}
        expandCitations={sonara.expandCitations}
        onExpandCitationsChange={sonara.setExpandCitations}
      />

      <NarrationPreviewModal
        isOpen={previewOpen}
        onClose={() => setPreviewOpen(false)}
        preview={narrationPreview}
        loading={previewLoading}
        error={previewError}
      />

      <HistoryDrawer
        isOpen={sonara.isHistoryOpen}
        onClose={() => sonara.setIsHistoryOpen(false)}
        recentDocs={sonara.recentDocs}
        onClearHistory={sonara.clearHistory}
      />

      <AssistantDrawer
        isOpen={sonara.isAssistantOpen}
        onClose={() => sonara.setIsAssistantOpen(false)}
        session={sonara.session}
        documentName={sonara.documentName}
        onOpenSettings={() => {
          sonara.setIsAssistantOpen(false);
          sonara.setIsSettingsOpen(true);
        }}
      />
    </main>
  );
}

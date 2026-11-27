import { useEffect, useMemo, useState } from "react";
import { TopBar } from "./components/TopBar";
import { DocumentCard } from "./components/DocumentCard";
import { PlayerCard } from "./components/PlayerCard";
import { type JumpTarget, ReaderPanel } from "./components/ReaderPanel";
import { ShortcutsModal } from "./components/ShortcutsModal";
import { SettingsModal } from "./components/SettingsModal";
import { HistoryDrawer } from "./components/HistoryDrawer";
import { AssistantDrawer } from "./components/AssistantDrawer";
import { NarrationPreviewModal } from "./components/NarrationPreviewModal";
import { isListeningPhase, useSonara } from "./hooks/useSonara";
import { isModalDialogOpen } from "./hooks/useModalDialog";
import type { NarrationPreview } from "./lib/tauri";
import { ArrowLeft, BookOpenText, History, House, Info, Library, Play, Plus, Search, Settings, ShieldCheck, Star, SunMoon, X } from "lucide-react";

function formatDuration(seconds: number): string {
  const totalMinutes = Math.max(0, Math.floor(seconds / 60));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (seconds < 60) return `${Math.round(Math.max(0, seconds))} sec`;
  return hours ? `${hours} hr ${minutes} min` : `${totalMinutes} min`;
}

function formatDocumentType(sourceName: string): string {
  const separator = sourceName.lastIndexOf(".");
  return separator >= 0 && separator < sourceName.length - 1
    ? sourceName.slice(separator + 1, separator + 6).toUpperCase()
    : "FILE";
}

/** One tick per passage, the current one lit: Sonara's passage strip. */
function PassageStrip({ count, current }: { count: number; current: number }) {
  if (count < 2 || count > 64) return null;
  return (
    <span className="passage-strip" aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <i key={index} className={index === current ? "is-current" : index < current ? "is-done" : undefined} />
      ))}
    </span>
  );
}

export default function App() {
  const sonara = useSonara();
  const [page, setPage] = useState<"home" | "library" | "reader" | "about">("home");
  type Page = typeof page;
  const navigate = (next: Page) => {
    // A citation is shown once; coming back to the reader later follows the player.
    if (next !== "reader") setJumpTarget(null);
    setPage(next);
  };
  // A passage the assistant cited, to show in the reader.
  const [jumpTarget, setJumpTarget] = useState<JumpTarget | null>(null);
  const canShowInReader = Boolean(sonara.session) && isListeningPhase(sonara.phase);
  const [libraryQuery, setLibraryQuery] = useState("");
  const [libraryFilter, setLibraryFilter] = useState<"all" | "favorites">("all");
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    try { return localStorage.getItem("sonara_theme") === "light" ? "light" : "dark"; } catch { return "dark"; }
  });
  const [favorites, setFavorites] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("sonara_favorites") || "[]") as string[]; } catch { return []; }
  });
  const filteredDocs = useMemo(() => sonara.recentDocs.filter((doc) => {
    const matchesQuery = doc.sourceName.toLocaleLowerCase().includes(libraryQuery.trim().toLocaleLowerCase());
    return matchesQuery && (libraryFilter === "all" || favorites.includes(doc.sourceSha256));
  }), [favorites, libraryFilter, libraryQuery, sonara.recentDocs]);
  const currentProgress = sonara.playerState.totalDuration > 0
    ? Math.min(100, Math.max(0, sonara.playerState.globalPosition / sonara.playerState.totalDuration * 100))
    : 0;
  const toggleFavorite = (id: string) => setFavorites((current) => {
    const next = current.includes(id) ? current.filter((value) => value !== id) : [...current, id];
    try { localStorage.setItem("sonara_favorites", JSON.stringify(next)); } catch { /* storage may be unavailable */ }
    return next;
  });
  const chooseFromLibrary = async () => {
    await sonara.chooseDocument();
    navigate("home");
  };
  const openFromLibrary = async (sourceSha256: string) => {
    const outcome = await sonara.openRecentDocument(sourceSha256);
    if (outcome === "failed") return;
    sonara.setIsHistoryOpen(false);
    navigate(outcome === "current" ? "reader" : "home");
  };
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("sonara_theme", theme); } catch { /* storage may be unavailable */ }
  }, [theme]);
  useEffect(() => {
    const handleGlobalSearch = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === "k" && !isModalDialogOpen()) {
        event.preventDefault();
        navigate("library");
        requestAnimationFrame(() => document.getElementById("global-search-input")?.focus());
      }
    };
    window.addEventListener("keydown", handleGlobalSearch);
    return () => window.removeEventListener("keydown", handleGlobalSearch);
  }, []);
  const handleGlobalSearch = (value: string) => {
    setLibraryQuery(value);
    if (value) navigate("library");
  };
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

  return (
    <main className="app-layout" data-ui="sonara-app" data-player={sonara.session && isListeningPhase(sonara.phase) ? "true" : "false"}>
      <aside className="app-rail" aria-label="Sonara navigation">
        <button className="rail-brand" type="button" onClick={() => navigate("home")} aria-label="Sonara home">
          <span className="rail-brand-mark" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <path d="M5 10v4M9 7v10M13 4v16M17 8v8M21 10v4" />
            </svg>
          </span>
          <span>Sonara</span>
        </button>

        <nav className="rail-nav" aria-label="Primary">
          <button className={`rail-nav-item ${page === "home" ? "is-current" : ""}`} type="button" onClick={() => navigate("home")} title="Home">
            <House size={18} aria-hidden="true" />
            <span>Home</span>
          </button>
          <button className={`rail-nav-item ${page === "library" ? "is-current" : ""}`} type="button" onClick={() => navigate("library")} title="Library">
            <Library size={18} aria-hidden="true" />
            <span>Library</span><span className="nav-count">{sonara.recentDocs.length}</span>
          </button>
          <button className={`rail-nav-item ${page === "reader" ? "is-current" : ""}`} type="button" onClick={() => navigate("reader")} disabled={!sonara.session} title="Reading view">
            <BookOpenText size={18} aria-hidden="true" />
            <span>Reading view</span>
          </button>
          <button className="rail-nav-item" type="button" aria-label="Listening history" onClick={() => sonara.setIsHistoryOpen(true)} title="Listening history">
            <History size={18} aria-hidden="true" />
            <span>History</span>
          </button>
          <button className="rail-nav-item" type="button" onClick={() => sonara.setIsSettingsOpen(true)} title="Settings">
            <Settings size={18} aria-hidden="true" />
            <span>Settings</span>
          </button>
          <button className={`rail-nav-item ${page === "about" ? "is-current" : ""}`} type="button" onClick={() => navigate("about")} aria-current={page === "about" ? "page" : undefined} title="About Sonara">
            <Info size={18} aria-hidden="true" />
            <span>About</span>
          </button>
          <button className="rail-nav-item" type="button" onClick={() => setTheme((value) => value === "dark" ? "light" : "dark")} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} appearance`} title="Appearance">
            <SunMoon size={18} aria-hidden="true" />
            <span>Appearance</span>
          </button>
        </nav>

        <div className="rail-note">
          <span className="rail-note-mark" aria-hidden="true" />
          <span><strong>Runs on this device</strong><small>Extraction and narration stay local</small></span>
        </div>
      </aside>

      <div className="app-frame" id="home">
        <TopBar
          historyCount={sonara.recentDocs.length}
          onOpenHistory={() => sonara.setIsHistoryOpen(true)}
          onOpenSettings={() => sonara.setIsSettingsOpen(true)}
          onOpenShortcuts={() => sonara.setIsShortcutsOpen(true)}
          onOpenAssistant={() => sonara.setIsAssistantOpen(true)}
          searchValue={libraryQuery}
          onSearchChange={handleGlobalSearch}
        />

        <div className="workspace-content">
          {page === "library" ? (
            <section className="product-page" aria-labelledby="library-title">
              <header className="page-heading"><div><h1 id="library-title">Library</h1><p className="subtitle">Documents prepared for listening, kept on this device</p></div><button className="button button-primary" type="button" onClick={() => void chooseFromLibrary()} disabled={!sonara.tauriReady}><Plus size={16} aria-hidden="true" />Import document</button></header>
              <div className="library-toolbar"><label className="library-search"><Search size={16} aria-hidden="true" /><input aria-label="Search your library" placeholder="Search" value={libraryQuery} onChange={(event) => setLibraryQuery(event.target.value)} />{libraryQuery && <button type="button" aria-label="Clear search" onClick={() => setLibraryQuery("")}><X size={16} aria-hidden="true" /></button>}</label><div className="filter-tabs" role="group" aria-label="Library filter"><button type="button" className={libraryFilter === "all" ? "active" : ""} onClick={() => setLibraryFilter("all")}>All documents</button><button type="button" className={libraryFilter === "favorites" ? "active" : ""} onClick={() => setLibraryFilter("favorites")}>Favorites</button></div></div>
              {filteredDocs.length ? <ul className="library-list">{filteredDocs.map((doc) => <li className="library-row" key={doc.sourceSha256}><span className="recent-file-mark">{formatDocumentType(doc.sourceName)}</span><div className="library-copy"><strong title={doc.sourceName}>{doc.sourceName}</strong><span>{doc.chunksCount} passages <i>·</i> {formatDuration(doc.totalDurationSeconds)} <i>·</i> {new Date(doc.lastListenedAt).toLocaleDateString()}</span></div><button className={`favorite-button ${favorites.includes(doc.sourceSha256) ? "is-favorite" : ""}`} type="button" aria-label={`${favorites.includes(doc.sourceSha256) ? "Remove from" : "Add to"} favorites: ${doc.sourceName}`} onClick={() => toggleFavorite(doc.sourceSha256)}><Star size={16} fill={favorites.includes(doc.sourceSha256) ? "currentColor" : "none"} aria-hidden="true" /></button>{sonara.session?.sourceSha256 === doc.sourceSha256
                ? <button className="button button-secondary" type="button" onClick={() => navigate("reader")}>Open reader</button>
                : <button className="button button-secondary" type="button" onClick={() => void openFromLibrary(doc.sourceSha256)} disabled={!doc.available} title={doc.available ? undefined : "The file was moved or deleted. Import it again."} aria-label={`Listen again: ${doc.sourceName}`}>Listen again</button>}</li>)}</ul> : <div className="library-empty"><h2>{sonara.recentDocs.length ? "No matching documents" : "No documents yet"}</h2><p>{sonara.recentDocs.length ? "Try another title or change the filter." : "Imported documents appear here once their speech is prepared."}</p>{!sonara.recentDocs.length && <button className="button button-primary" type="button" onClick={() => void chooseFromLibrary()} disabled={!sonara.tauriReady}>Import a document</button>}</div>}
            </section>
          ) : page === "about" ? (
            <section className="product-page about-page" aria-labelledby="about-title">
              <header className="about-intro">
                <span className="about-mark" aria-hidden="true">
                  <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M5 10v4M9 7v10M13 4v16M17 8v8M21 10v4"/></svg>
                </span>
                <div>
                                    <h1 id="about-title">About Sonara</h1>
                  <p className="subtitle">Sonara reads your documents aloud with a voice that runs on this device, and highlights each passage as it is spoken.</p>
                </div>
              </header>

              <section className="about-story" aria-labelledby="about-story-title">
                <div className="about-story-copy">
                  <h2 id="about-story-title">For papers, reports and long articles</h2>
                  <p>Listen to a document while you follow its text, pause anywhere, and come back to the same passage later.</p>
                </div>
                <button className="button button-primary" type="button" onClick={() => navigate("library")}>Explore your library</button>
              </section>

              <section className="about-capabilities" aria-label="How Sonara works">
                <article className="about-capability">
                  <span className="about-capability-index">01</span>
                  <h2>Import a document</h2>
                  <p>PDF, Word, EPUB, Markdown or plain text. Scanned PDFs are read with OCR.</p>
                </article>
                <article className="about-capability">
                  <span className="about-capability-index">02</span>
                  <h2>Choose a voice and speed</h2>
                  <p>Piper or Kokoro voices, from 0.7× to 1.5×.</p>
                </article>
                <article className="about-capability">
                  <span className="about-capability-index">03</span>
                  <h2>Resume where you stopped</h2>
                  <p>Sonara remembers the passage you reached in each document.</p>
                </article>
              </section>

              <aside className="about-privacy" aria-labelledby="about-privacy-title">
                <span className="privacy-icon" aria-hidden="true">
                  <ShieldCheck size={18} aria-hidden="true" />
                </span>
                <div>
                  <h2 id="about-privacy-title">Private by default</h2>
                  <p>Document extraction and Piper narration run on this device. Assistant providers are separate and are used only when you choose an assistant feature.</p>
                </div>
                <button className="continue-text-action" type="button" onClick={() => sonara.setIsSettingsOpen(true)}>Review settings</button>
              </aside>
            </section>
          ) : page === "reader" && sonara.session && isListeningPhase(sonara.phase) ? (
            <section className="reader-page"><button className="back-link" type="button" onClick={() => navigate("home")}><ArrowLeft size={16} aria-hidden="true" />Home</button><ReaderPanel
              sourceName={sonara.session.sourceName}
              sourceSha256={sonara.session.sourceSha256}
              chunks={sonara.session.chunks}
              activeChunk={sonara.playerState.segment}
              onPlayFromChunk={(index) => sonara.seekToChunk(index, true)}
              jumpTarget={jumpTarget}
            /></section>
          ) : <>
          {!sonara.tauriReady && (
            <aside className="banner-preview" role="note" aria-label="Runtime notice">
              <div className="banner-icon" aria-hidden="true">i</div>
              <div className="banner-text">
                <strong>Browser preview</strong>
                <span>Open Sonara as a desktop app to import a document and generate local Piper narration.</span>
              </div>
            </aside>
          )}

          <header className="intro home-intro" aria-labelledby="page-title">
            <div className="home-intro-copy">
              <h1 id="page-title">Listen to your documents</h1>
              <p className="subtitle">Sonara reads PDF, Word, EPUB, Markdown and text files aloud on this device, and highlights each passage as it speaks.</p>
            </div>
            <button className="button button-primary home-import-button" type="button" onClick={sonara.chooseDocument} disabled={!sonara.tauriReady}>
              <Plus size={16} aria-hidden="true" />
              Import a document
            </button>
          </header>

          {sonara.recentDocs.length > 0 && <section className="home-stats" aria-label="Your listening overview">
            <article className="home-stat"><span className="home-stat-copy"><small>In your library</small><strong>{sonara.recentDocs.length}</strong><span>{sonara.recentDocs.length === 1 ? "document" : "documents"} prepared</span></span></article>
            <article className="home-stat"><span className="home-stat-copy"><small>Favorites</small><strong>{favorites.length}</strong><span>marked in the library</span></span></article>
            <article className="home-stat"><span className="home-stat-copy"><small>Current document</small><strong>{sonara.session ? `${Math.round(currentProgress)}%` : "0%"}</strong><span>{sonara.session ? `passage ${sonara.playerState.segment + 1} of ${sonara.session.chunks.length}` : "no document open"}</span></span></article>
          </section>}

          <div className="workspace-grid">
            <section className="workspace-primary" aria-label="Current listening and document import">
              {sonara.session && isListeningPhase(sonara.phase) && (() => {
                return <section className="continue-card" aria-labelledby="continue-title">
                  <div className="continue-art" aria-hidden="true"><span className="continue-page"><span className="continue-file-kind">{formatDocumentType(sonara.session.sourceName)}</span><i /><i /><i className="is-lit" /><i /><i /><i /></span></div>
                  <div className="continue-copy">
                    <span className="eyebrow">Continue listening</span>
                    <h2 id="continue-title" title={sonara.session.sourceName}>{sonara.session.sourceName}</h2>
                    <p>{sonara.playerState.totalDuration ? `${formatDuration(sonara.playerState.totalDuration)} · ` : ""}Passage {sonara.playerState.segment + 1} of {sonara.session.chunks.length}</p>
                    <PassageStrip count={sonara.session.chunks.length} current={sonara.playerState.segment} />
                    <div className="continue-progress" role="progressbar" aria-label="Listening progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(currentProgress)}><span style={{ width: `${currentProgress}%` }} /></div>
                    <div className="continue-time"><span>{formatDuration(sonara.playerState.globalPosition)} listened</span><span>{Math.round(currentProgress)}%</span></div>
                    <div className="continue-actions"><button className="button button-primary" type="button" onClick={() => void sonara.startPlayback()} disabled={sonara.playerState.isPlaying || sonara.playerState.hasError}><Play size={16} fill="currentColor" aria-hidden="true" /><span>{sonara.playerState.isPlaying ? "Listening now" : "Resume listening"}</span></button><button className="continue-text-action" type="button" onClick={() => navigate("reader")}>Read along</button></div>
                  </div>
                </section>;
              })()}

              <section className="import-section" aria-labelledby="import-heading">
                <div className="section-heading">
                  <div>
                    <h2 id="import-heading">{sonara.session ? "Import another document" : "Import a document"}</h2>
                    <p>PDF, TXT, MD, DOCX or EPUB. Text extraction and speech run on this device.</p>
                  </div>
                </div>
                <DocumentCard
                  phase={sonara.phase}
                  documentName={sonara.documentName}
                  statusText={sonara.statusText}
                  errorText={sonara.errorText}
                  disabled={!sonara.tauriReady}
                  selectedVoiceName={sonara.selectedVoiceName}
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
                    <h2 id="recent-title">Recently prepared</h2>
                    {!sonara.recentDocs.length && <p>Prepared documents appear here</p>}
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
                        <span className="recent-file-mark" data-kind={formatDocumentType(doc.sourceName)} aria-hidden="true">{formatDocumentType(doc.sourceName)}</span>
                        <span className="recent-copy">
                          <strong title={doc.sourceName}>{doc.sourceName}</strong>
                          <small>{doc.chunksCount} passages <span aria-hidden="true">·</span> {formatDuration(doc.totalDurationSeconds)}</small>
                          <small>{new Date(doc.lastListenedAt).toLocaleDateString()}</small>
                        </span>
                        <button className="quiet-action" type="button" onClick={() => void openFromLibrary(doc.sourceSha256)} disabled={!doc.available && sonara.session?.sourceSha256 !== doc.sourceSha256} aria-label={`Open ${doc.sourceName}`}>Open</button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="recent-empty">
                    <p>Nothing prepared yet</p>
                  </div>
                )}
              </section>

              <div className="privacy-note">
                <span className="privacy-icon" aria-hidden="true">
                  <ShieldCheck size={18} aria-hidden="true" />
                </span>
                <span><strong>Private by default</strong><small>Document extraction and Piper narration run on this device. Assistant providers are separate.</small></span>
              </div>
            </aside>
          </div>

          </>}
        </div>
        {sonara.session && isListeningPhase(sonara.phase) && (
          <PlayerCard
            session={sonara.session} state={sonara.playerState}
            voiceLabel={[...sonara.voices, ...sonara.kokoroVoices].find((voice) => voice.id === sonara.session?.voice)?.name}
            audioRef={sonara.attachAudio} chunkStarts={sonara.chunkStarts}
            onPlay={sonara.startPlayback} onPause={sonara.pausePlayback} onSeek={sonara.seekTo}
            onSeekChunk={sonara.seekToChunk} onSpeedChange={(rate) => sonara.setSpeed(rate)}
            onRetry={sonara.retryPassage} onSkip={sonara.skipPassage}
            onLoadedMetadata={sonara.handleLoadedMetadata} onTimeUpdate={sonara.handleTimeUpdate}
            onError={sonara.handleError} onPlaying={sonara.handlePlaying} onEnded={sonara.handleEnded}
            onCanPlay={sonara.handleCanPlay} onWaiting={sonara.handleWaiting}
          />
        )}
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
        kokoroVoices={sonara.kokoroVoices}
        onModelsChanged={sonara.refreshVoices}
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
        onClearHistory={() => void sonara.clearHistory()}
        onOpenDocument={(sha) => void openFromLibrary(sha)}
        currentSha256={sonara.session?.sourceSha256}
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
        onOpenCitation={canShowInReader ? (citation) => {
          const span = citation.spans[0];
          if (!span) return;
          sonara.setIsAssistantOpen(false);
          setJumpTarget({ ...span, key: Date.now() });
          navigate("reader");
        } : undefined}
      />
    </main>
  );
}

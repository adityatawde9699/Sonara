import { useEffect, useMemo, useState } from "react";
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
  const [page, setPage] = useState<"home" | "library" | "reader" | "about">("home");
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
    setPage("home");
  };
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("sonara_theme", theme); } catch { /* storage may be unavailable */ }
  }, [theme]);
  useEffect(() => {
    const handleGlobalSearch = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === "k") {
        event.preventDefault();
        setPage("library");
        requestAnimationFrame(() => document.getElementById("global-search-input")?.focus());
      }
    };
    window.addEventListener("keydown", handleGlobalSearch);
    return () => window.removeEventListener("keydown", handleGlobalSearch);
  }, []);
  const handleGlobalSearch = (value: string) => {
    setLibraryQuery(value);
    if (value) setPage("library");
  };
  const [isPolishEnabled, setIsPolishEnabled] = useState(() => {
    try { return localStorage.getItem(AI_NARRATION_POLISH_STORAGE_KEY) === "true"; } catch { return false; }
  });
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
    <main className="app-layout" data-ui="sonara-app" data-player={sonara.session && sonara.phase === "ready" ? "true" : "false"}>
      <aside className="app-rail" aria-label="Sonara navigation">
        <button className="rail-brand" type="button" onClick={() => setPage("home")} aria-label="Sonara home">
          <span className="rail-brand-mark" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <path d="M5 10v4M9 7v10M13 4v16M17 8v8M21 10v4" />
            </svg>
          </span>
          <span>Sonara</span>
        </button>

        <nav className="rail-nav" aria-label="Primary">
          <button className={`rail-nav-item ${page === "home" ? "is-current" : ""}`} type="button" onClick={() => setPage("home")} title="Home">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="9" />
              <path d="m10 8 6 4-6 4V8Z" />
            </svg>
            <span>Home</span>
          </button>
          <button className={`rail-nav-item ${page === "library" ? "is-current" : ""}`} type="button" onClick={() => setPage("library")} title="My Library">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 1 4 17.5z"/><path d="M4 17.5A2.5 2.5 0 0 1 6.5 15H20M8 7h8M8 10h8"/></svg>
            <span>My Library</span><span className="nav-count">{sonara.recentDocs.length}</span>
          </button>
          <button className={`rail-nav-item ${page === "reader" ? "is-current" : ""}`} type="button" onClick={() => setPage("reader")} disabled={!sonara.session} title="Reading view">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 1 4 17.5z"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>
            <span>Reading view</span>
          </button>
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
          <button className={`rail-nav-item ${page === "about" ? "is-current" : ""}`} type="button" onClick={() => setPage("about")} aria-current={page === "about" ? "page" : undefined} title="About Sonara">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/></svg>
            <span>About</span>
          </button>
          <button className="rail-nav-item" type="button" onClick={() => setTheme((value) => value === "dark" ? "light" : "dark")} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} appearance`} title="Appearance">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg>
            <span>Appearance</span>
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
          searchValue={libraryQuery}
          onSearchChange={handleGlobalSearch}
        />

        <div className="workspace-content">
          {page === "library" ? (
            <section className="product-page" aria-labelledby="library-title">
              <header className="page-heading"><div><span className="eyebrow">YOUR COLLECTION</span><h1 id="library-title">My library</h1><p className="subtitle">Documents prepared for listening, kept on this device.</p></div><button className="button button-primary" type="button" onClick={() => void chooseFromLibrary()} disabled={!sonara.tauriReady}>＋ Import document</button></header>
              <div className="library-toolbar"><label className="library-search"><span aria-hidden="true">⌕</span><input aria-label="Search your library" placeholder="Search documents" value={libraryQuery} onChange={(event) => setLibraryQuery(event.target.value)} />{libraryQuery && <button type="button" aria-label="Clear search" onClick={() => setLibraryQuery("")}>×</button>}</label><div className="filter-tabs" role="group" aria-label="Library filter"><button type="button" className={libraryFilter === "all" ? "active" : ""} onClick={() => setLibraryFilter("all")}>All documents</button><button type="button" className={libraryFilter === "favorites" ? "active" : ""} onClick={() => setLibraryFilter("favorites")}>Favorites</button></div></div>
              {filteredDocs.length ? <ul className="library-list">{filteredDocs.map((doc) => <li className="library-row" key={doc.sourceSha256}><span className="recent-file-mark">{formatDocumentType(doc.sourceName)}</span><div className="library-copy"><strong title={doc.sourceName}>{doc.sourceName}</strong><span>{doc.chunksCount} passages <i>·</i> {formatDuration(doc.totalDurationSeconds)} <i>·</i> {new Date(doc.lastListenedAt).toLocaleDateString()}</span></div><button className={`favorite-button ${favorites.includes(doc.sourceSha256) ? "is-favorite" : ""}`} type="button" aria-label={`${favorites.includes(doc.sourceSha256) ? "Remove from" : "Add to"} favorites: ${doc.sourceName}`} onClick={() => toggleFavorite(doc.sourceSha256)}>{favorites.includes(doc.sourceSha256) ? "★" : "☆"}</button>{sonara.session?.sourceSha256 === doc.sourceSha256 && <button className="button button-secondary" type="button" onClick={() => setPage("reader")}>Open reader</button>}</li>)}</ul> : <div className="library-empty"><span className="empty-icon" aria-hidden="true">⌕</span><h2>{sonara.recentDocs.length ? "No matching documents" : "Your library is waiting"}</h2><p>{sonara.recentDocs.length ? "Try another title or change the filter." : "Import a document and it will be ready to listen to here."}</p>{!sonara.recentDocs.length && <button className="button button-primary" type="button" onClick={() => void chooseFromLibrary()} disabled={!sonara.tauriReady}>Import a document</button>}</div>}
            </section>
          ) : page === "about" ? (
            <section className="product-page about-page" aria-labelledby="about-title">
              <header className="about-intro">
                <span className="about-mark" aria-hidden="true">
                  <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M5 10v4M9 7v10M13 4v16M17 8v8M21 10v4"/></svg>
                </span>
                <div>
                  <span className="eyebrow">ABOUT SONARA</span>
                  <h1 id="about-title">Your documents, ready to listen.</h1>
                  <p className="subtitle">Sonara turns the things you read into a listening experience you can follow, pause, and return to.</p>
                </div>
              </header>

              <section className="about-story" aria-labelledby="about-story-title">
                <div className="about-story-copy">
                  <h2 id="about-story-title">Made for the moments between reading.</h2>
                  <p>Research papers, reports, notes, and long articles deserve a place in your day beyond the screen. Sonara brings narration and source text together, so you can listen while you follow along at your own pace.</p>
                </div>
                <button className="button button-primary" type="button" onClick={() => setPage("library")}>Explore your library</button>
              </section>

              <section className="about-capabilities" aria-label="How Sonara works">
                <article className="about-capability">
                  <span className="about-capability-index">01</span>
                  <h2>Bring what you’re reading</h2>
                  <p>Prepare a PDF, text, Markdown, Word, or EPUB document in your personal library.</p>
                </article>
                <article className="about-capability">
                  <span className="about-capability-index">02</span>
                  <h2>Make it sound like yours</h2>
                  <p>Choose an available narration voice and adjust playback speed to suit the moment.</p>
                </article>
                <article className="about-capability">
                  <span className="about-capability-index">03</span>
                  <h2>Pick up where you left off</h2>
                  <p>Your recent documents and listening position help make the next session easy to resume.</p>
                </article>
              </section>

              <aside className="about-privacy" aria-labelledby="about-privacy-title">
                <span className="privacy-icon" aria-hidden="true">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/></svg>
                </span>
                <div>
                  <h2 id="about-privacy-title">Private by default</h2>
                  <p>Document extraction and Piper narration run on this device. Assistant providers are separate and are used only when you choose an assistant feature.</p>
                </div>
                <button className="continue-text-action" type="button" onClick={() => sonara.setIsSettingsOpen(true)}>Review settings <span aria-hidden="true">↗</span></button>
              </aside>
            </section>
          ) : page === "reader" && sonara.session && sonara.phase === "ready" ? (
            <section className="reader-page"><button className="back-link" type="button" onClick={() => setPage("home")}>← Back to Home</button><ReaderPanel sourceName={sonara.session.sourceName} sourceSha256={sonara.session.sourceSha256} /></section>
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

          <header className={`intro home-intro ${sonara.session ? "has-session" : ""}`} aria-labelledby="page-title">
            <div className="home-intro-copy">
              <span className="eyebrow">A PERSONAL LISTENING SPACE</span>
              <h1 id="page-title">{sonara.session ? "Welcome back to your story." : "What would you like to listen to?"}</h1>
              <p className="subtitle">{sonara.session ? "Your place is saved. Settle in and pick up where you left off." : "Bring a document. We’ll turn it into a listening experience, right here on your device."}</p>
              <button className="button button-primary home-import-button" type="button" onClick={sonara.chooseDocument} disabled={!sonara.tauriReady}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
                Import a document
              </button>
            </div>
            <div className="home-intro-art" aria-hidden="true">
              <span className="intro-art-glow" />
              <svg viewBox="0 0 300 180" fill="none"><path d="M18 91h23l12-34 18 70 16-51 17 31 14-17h18l14-40 19 79 17-48 14 21h22l13-31 18 42 12-22h28" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/><path d="M29 140h240" stroke="currentColor" strokeOpacity=".25" strokeWidth="1"/><circle cx="150" cy="91" r="60" stroke="currentColor" strokeOpacity=".12"/><circle cx="150" cy="91" r="78" stroke="currentColor" strokeOpacity=".08"/></svg>
              <span className="intro-art-caption">YOUR WORDS, YOUR PACE</span>
            </div>
          </header>

          {sonara.recentDocs.length > 0 && <section className="home-stats" aria-label="Your listening overview">
            <article className="home-stat"><span className="home-stat-copy"><small>Prepared documents</small><strong>{sonara.recentDocs.length}</strong><span>ready in your library</span></span></article>
            <article className="home-stat"><span className="home-stat-copy"><small>Saved for later</small><strong>{favorites.length}</strong><span>favorite documents</span></span></article>
            <article className="home-stat"><span className="home-stat-copy"><small>Listening progress</small><strong>{sonara.session ? `${Math.round(currentProgress)}%` : "—"}</strong><span>{sonara.session ? `passage ${sonara.playerState.segment + 1} of ${sonara.session.chunks.length}` : "ready when you are"}</span></span></article>
          </section>}

          <div className="workspace-grid">
            <section className="workspace-primary" aria-label="Current listening and document import">
              {sonara.session && sonara.phase === "ready" && (() => {
                return <section className="continue-card" aria-labelledby="continue-title">
                  <div className="continue-art" aria-hidden="true"><span className="continue-file-kind">{formatDocumentType(sonara.session.sourceName)}</span><svg viewBox="0 0 120 90" fill="none"><path d="M8 46h13l8-22 13 44 13-34 11 23 10-11h12l9-28 13 55 9-36 9 16h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg><small>READY WHEN YOU ARE</small></div>
                  <div className="continue-copy">
                    <span className="eyebrow">CONTINUE LISTENING</span>
                    <h2 id="continue-title" title={sonara.session.sourceName}>{sonara.session.sourceName}</h2>
                    <p>{sonara.playerState.totalDuration ? `${formatDuration(sonara.playerState.totalDuration)} · ` : ""}Passage {sonara.playerState.segment + 1} of {sonara.session.chunks.length}</p>
                    <div className="continue-progress" role="progressbar" aria-label="Listening progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(currentProgress)}><span style={{ width: `${currentProgress}%` }} /></div>
                    <div className="continue-time"><span>{formatDuration(sonara.playerState.globalPosition)} listened</span><span>{Math.round(currentProgress)}%</span></div>
                    <div className="continue-actions"><button className="button button-primary" type="button" onClick={() => void sonara.startPlayback()} disabled={sonara.playerState.isPlaying || sonara.playerState.hasError}>▶ <span>{sonara.playerState.isPlaying ? "Listening now" : "Resume listening"}</span></button><button className="continue-text-action" type="button" onClick={() => setPage("reader")}>Read along <span aria-hidden="true">↗</span></button></div>
                  </div>
                </section>;
              })()}

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
                    <h2 id="recent-title">Recently prepared</h2>
                    <p>{sonara.recentDocs.length ? "A few good places to pick up" : "Your prepared documents will appear here"}</p>
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
          </>}
        </div>
        {sonara.session && sonara.phase === "ready" && (
          <PlayerCard
            session={sonara.session} state={sonara.playerState}
            voiceLabel={sonara.voices.find((voice) => voice.id === sonara.session?.voice)?.name}
            audioRef={sonara.audioRef} chunkStarts={sonara.chunkStarts}
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
        onPolishChange={setIsPolishEnabled}
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

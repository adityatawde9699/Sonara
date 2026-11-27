import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import {
  type FrontendSession,
  type LibraryDocument,
  type NarrationPreview,
  type SynthesisProgress,
  pickDocument,
  currentSession,
  streamingSession,
  startReading,
  cancelReading,
  onSynthesisFinished,
  onSynthesisProgress,
  isTauriAvailable,
  previewNarration as fetchNarrationPreview,
  listLibrary,
  openLibraryDocument,
  clearLibrary,
} from "../lib/tauri";
import { isModalDialogOpen } from "./useModalDialog";
import { getChunkStarts, useAudioPlayer } from "./useAudioPlayer";
import { DEFAULT_PIPER_VOICE, useSpeechSettings } from "./useSpeechSettings";

export type { PlayerState } from "./useAudioPlayer";

export type AppPhase =
  | "idle"
  | "selected"
  | "synthesizing"
  /** The first passages are playable while the rest are synthesized. */
  | "streaming"
  | "ready"
  | "error";

/** Phases in which a session can be listened to. */
export function isListeningPhase(phase: AppPhase): boolean {
  return phase === "ready" || phase === "streaming";
}

/** History kept in WebView storage before the desktop library existed. It has
 * no file paths, so its rows could never be reopened. */
const LEGACY_HISTORY_KEY = "sonara_recent_documents";

export type OpenDocumentOutcome = "current" | "selected" | "failed";

const COMPOSITE_WIDGETS =
  "[role='slider'], [role='tab'], [role='tablist'], [role='listbox'], [role='option'], [role='menu'], [role='menuitem'], [role='radiogroup']";

/**
 * Application state: the document phase (pick → synthesize → listen), the
 * synthesis worker events, history, dialogs and keyboard shortcuts. Playback
 * lives in `useAudioPlayer`, voice and narration options in
 * `useSpeechSettings`.
 */
export function useSonara() {
  const tauriAvailable = isTauriAvailable();
  const [phase, setPhase] = useState<AppPhase>("idle");
  const [documentName, setDocumentName] = useState("");
  const [statusText, setStatusText] = useState("Your file stays on this device.");
  const [errorText, setErrorText] = useState(
    tauriAvailable ? "" : "Sonara desktop APIs are unavailable. Start the application through Tauri.",
  );
  const [session, setSession] = useState<FrontendSession | null>(null);
  const [tauriReady] = useState(tauriAvailable);
  const [recentDocs, setRecentDocs] = useState<LibraryDocument[]>([]);
  const chunkStarts = useMemo(() => getChunkStarts(session?.chunks ?? []), [session]);

  const [isShortcutsOpen, setIsShortcutsOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isAssistantOpen, setIsAssistantOpen] = useState(false);

  // Event handlers registered once read the latest phase and session here.
  const phaseRef = useRef<AppPhase>("idle");
  const sessionRef = useRef<FrontendSession | null>(null);
  // The session open before a streaming run, restored if that run fails.
  const previousSessionRef = useRef<FrontendSession | null>(null);
  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  const settings = useSpeechSettings(tauriAvailable);
  const player = useAudioPlayer();
  const { openSession, appendChunks, completeSession, suspend, togglePlayback, seekRelative, seekTo, seekToEnd, adjustSpeed } = player;
  const { selectedVoice, piperVariation, expandDates, expandCitations, speechEngine, resourceProfile } = settings;

  // ── Sessions and the library ────────────────────────────────────

  const refreshLibrary = useCallback(async () => {
    try {
      setRecentDocs(await listLibrary());
    } catch {
      /* the library is optional; keep what is shown */
    }
  }, []);

  const showSession = useCallback(async (nextSession: FrontendSession) => {
    setSession(nextSession);
    sessionRef.current = nextSession;
    setDocumentName(nextSession.sourceName);
    setStatusText(`Ready to listen · ${nextSession.chunks.length} passages · ${nextSession.voice}`);
    setPhase("ready");
    phaseRef.current = "ready";
    // The backend records a finished document before announcing it.
    void refreshLibrary();
    await openSession(nextSession);
  }, [openSession, refreshLibrary]);

  const streamingStatus = (ready: number, total: number) =>
    `Listen now while the rest is prepared · ${ready} of ${total} passages ready`;

  /** The first passages of a run are ready: open them while the rest synthesize. */
  const startStreaming = useCallback(async (partial: FrontendSession, totalChunks: number) => {
    previousSessionRef.current = sessionRef.current;
    setSession(partial);
    sessionRef.current = partial;
    setDocumentName(partial.sourceName);
    setStatusText(streamingStatus(partial.chunks.length, totalChunks));
    setPhase("streaming");
    phaseRef.current = "streaming";
    await openSession(partial, { expectedChunks: totalChunks });
  }, [openSession]);

  const handleSynthesisProgress = useCallback(async (payload: SynthesisProgress) => {
    const { completedChunks, totalChunks } = payload;
    if (payload.session) {
      await startStreaming(payload.session, totalChunks);
      return;
    }
    if (phaseRef.current !== "streaming") {
      const pct = totalChunks > 0 ? Math.round((completedChunks / totalChunks) * 100) : 0;
      setStatusText(`Synthesizing speech: passage ${completedChunks} of ${totalChunks} (${pct}%)…`);
      return;
    }
    let grown = appendChunks(payload.firstChunk, payload.newChunks, totalChunks);
    if (!grown) {
      // An event was missed; catch up from the backend's copy of the run.
      const snapshot = await streamingSession().catch(() => null);
      const current = sessionRef.current;
      if (snapshot && current && snapshot.session.sourceSha256 === current.sourceSha256) {
        grown = appendChunks(
          current.chunks.length,
          snapshot.session.chunks.slice(current.chunks.length),
          snapshot.totalChunks,
        );
      }
    }
    if (grown) {
      setSession(grown);
      sessionRef.current = grown;
      setStatusText(streamingStatus(grown.chunks.length, totalChunks));
    }
  }, [appendChunks, startStreaming]);

  const handleClearHistory = useCallback(async () => {
    try {
      await clearLibrary();
      setRecentDocs([]);
    } catch (error) {
      setErrorText(String(error));
    }
  }, []);

  // ── Document and synthesis ──────────────────────────────────────

  const chooseDocument = useCallback(async () => {
    suspend();
    try {
      const selected = await pickDocument();
      if (!selected) return;
      setDocumentName(selected.displayName);
      setStatusText("Selected on this device · ready to prepare speech");
      setErrorText("");
      setPhase("selected");
    } catch (error) {
      setErrorText(String(error));
    }
  }, [suspend]);

  /** Reopen a library document: the current one is already loaded;
   * any other is selected so it can be prepared again (mostly from cache). */
  const openRecentDocument = useCallback(async (sourceSha256: string): Promise<OpenDocumentOutcome> => {
    if (session?.sourceSha256 === sourceSha256) return "current";
    suspend();
    try {
      const selected = await openLibraryDocument(sourceSha256);
      setDocumentName(selected.displayName);
      setStatusText("Selected from your library · ready to prepare speech");
      setErrorText("");
      setPhase("selected");
      return "selected";
    } catch (error) {
      setErrorText(String(error));
      void refreshLibrary();
      return "failed";
    }
  }, [refreshLibrary, session, suspend]);

  const beginSynthesis = useCallback(async () => {
    suspend();
    setPhase("synthesizing");
    setStatusText(`Preparing speech with the local ${speechEngine === "kokoro" ? "Kokoro" : "Piper"} voice…`);
    try {
      await startReading(selectedVoice, piperVariation, expandDates, expandCitations, speechEngine, resourceProfile);
    } catch (error) {
      setPhase("selected");
      setErrorText(String(error));
    }
  }, [suspend, selectedVoice, piperVariation, expandDates, expandCitations, speechEngine, resourceProfile]);

  const previewCurrentNarration = useCallback((): Promise<NarrationPreview> => {
    // Kokoro has no Piper lexicon, so preview with the default Piper voice.
    return fetchNarrationPreview(speechEngine === "kokoro" ? DEFAULT_PIPER_VOICE : selectedVoice, expandDates, expandCitations);
  }, [selectedVoice, expandDates, expandCitations, speechEngine]);

  const cancelSynthesis = useCallback(async () => {
    try {
      await cancelReading();
      setStatusText("Stopping the local speech worker…");
    } catch (error) {
      setStatusText(String(error));
    }
  }, []);

  // ── Global keyboard shortcuts ───────────────────────────────────

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl/Cmd/Alt combinations belong to the browser and other handlers
      // (Ctrl+A selects, Ctrl+K opens search); only bare keys are shortcuts.
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
      // An open dialog owns the keyboard; it handles Escape itself.
      if (isModalDialogOpen()) return;
      const target = e.target instanceof HTMLElement ? e.target : null;
      if (
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.tagName === "SELECT" ||
        target?.isContentEditable
      ) {
        return;
      }
      // Let focused controls keep their own keys: Space/Enter activate a
      // button or link, and arrows/Home/End move within composite widgets.
      if ((e.key === " " || e.key === "Enter") && target?.closest("button, a[href], summary, [role='button']")) {
        return;
      }
      if (/^(Arrow|Home$|End$)/.test(e.key) && target?.closest(COMPOSITE_WIDGETS)) {
        return;
      }

      if (e.key === "?") {
        e.preventDefault();
        setIsShortcutsOpen((prev) => !prev);
        return;
      }
      if (e.key === "a" || e.key === "A") {
        e.preventDefault();
        setIsAssistantOpen((prev) => !prev);
        return;
      }

      // Media shortcuts require a session that can be listened to.
      if (!isListeningPhase(phase) || !session) return;

      const actions: Record<string, () => void> = {
        " ": togglePlayback,
        k: togglePlayback,
        ArrowLeft: () => seekRelative(-5),
        j: () => seekRelative(-5),
        ArrowRight: () => seekRelative(5),
        l: () => seekRelative(5),
        ArrowUp: () => adjustSpeed(0.1),
        "]": () => adjustSpeed(0.1),
        ArrowDown: () => adjustSpeed(-0.1),
        "[": () => adjustSpeed(-0.1),
        Home: () => seekTo(0),
        End: seekToEnd,
      };
      const action = actions[e.key.length === 1 ? e.key.toLowerCase() : e.key];
      if (action) {
        e.preventDefault();
        action();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [phase, session, togglePlayback, seekRelative, seekTo, seekToEnd, adjustSpeed]);

  // ── Worker events and the saved session ─────────────────────────

  useEffect(() => {
    if (!tauriAvailable) return;

    let unlistenFn: (() => void) | null = null;
    let unlistenProgressFn: (() => void) | null = null;

    const init = async () => {
      try {
        localStorage.removeItem(LEGACY_HISTORY_KEY);
      } catch {
        /* storage unavailable */
      }
      void refreshLibrary();

      try {
        unlistenFn = await onSynthesisFinished(async (payload) => {
          const wasStreaming = phaseRef.current === "streaming";
          if ("Ok" in payload.result) {
            const finished = payload.result.Ok;
            if (wasStreaming && sessionRef.current?.sourceSha256 === finished.sourceSha256) {
              // Keep playing where the listener is; the session is now whole.
              completeSession(finished);
              setSession(finished);
              sessionRef.current = finished;
              setStatusText(`Ready to listen · ${finished.chunks.length} passages · ${finished.voice}`);
              setPhase("ready");
              phaseRef.current = "ready";
              void refreshLibrary();
            } else {
              await showSession(finished);
            }
          } else {
            if (wasStreaming) {
              // The partial run is gone; go back to the session open before it.
              suspend();
              const previous = previousSessionRef.current;
              setSession(previous);
              sessionRef.current = previous;
              if (previous) await openSession(previous);
            }
            setPhase("selected");
            phaseRef.current = "selected";
            setErrorText(payload.result.Err || "Speech generation failed.");
          }
          previousSessionRef.current = null;
        });
      } catch {
        /* event listener unavailable */
      }

      try {
        unlistenProgressFn = await onSynthesisProgress((payload) => {
          void handleSynthesisProgress(payload);
        });
      } catch {
        /* progress listener unavailable */
      }

      try {
        const savedSession = await currentSession();
        if (savedSession) await showSession(savedSession);
      } catch (error) {
        setErrorText(String(error));
      }
    };

    void init();

    return () => {
      unlistenFn?.();
      unlistenProgressFn?.();
    };
  }, [completeSession, handleSynthesisProgress, openSession, refreshLibrary, showSession, suspend, tauriAvailable]);

  return {
    // State
    phase,
    documentName,
    statusText,
    errorText,
    session,
    playerState: player.playerState,
    tauriReady,
    audioRef: player.audioRef,
    attachAudio: player.attachAudio,
    chunkStarts,
    recentDocs,

    // Voice and narration settings
    voices: settings.voices,
    kokoroVoices: settings.kokoroVoices,
    refreshVoices: settings.refreshVoices,
    speechEngine,
    setSpeechEngine: settings.setSpeechEngine,
    resourceProfile,
    setResourceProfile: settings.setResourceProfile,
    selectedVoice,
    setSelectedVoice: settings.setSelectedVoice,
    piperVariation,
    setPiperVariation: settings.setPiperVariation,
    expandDates,
    setExpandDates: settings.setExpandDates,
    expandCitations,
    setExpandCitations: settings.setExpandCitations,
    previewCurrentNarration,
    selectedVoiceName: settings.selectedVoiceName,

    // Modals
    isShortcutsOpen,
    setIsShortcutsOpen,
    isSettingsOpen,
    setIsSettingsOpen,
    isHistoryOpen,
    setIsHistoryOpen,
    isAssistantOpen,
    setIsAssistantOpen,

    // Actions
    chooseDocument,
    openRecentDocument,
    beginSynthesis,
    cancelSynthesis,
    startPlayback: player.startPlayback,
    pausePlayback: player.pausePlayback,
    seekTo,
    seekToChunk: player.seekToChunk,
    seekRelative,
    setSpeed: player.setSpeed,
    retryPassage: player.retryPassage,
    skipPassage: player.skipPassage,
    clearHistory: handleClearHistory,

    // Audio event handlers
    handleLoadedMetadata: player.handleLoadedMetadata,
    handleTimeUpdate: player.handleTimeUpdate,
    handleError: player.handleError,
    handlePlaying: player.handlePlaying,
    handleEnded: player.handleEnded,
    handleCanPlay: player.handleCanPlay,
    handleWaiting: player.handleWaiting,
  };
}

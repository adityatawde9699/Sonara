import { useState, useRef, useCallback, useEffect } from "react";
import {
  type FrontendSession,
  type Progress,
  type VoiceInfo,
  type PiperVariation,
  type SpeechEngine,
  type ResourceProfile,
  type NarrationPreview,
  pickDocument,
  currentSession,
  listVoices,
  startReading,
  cancelReading,
  loadProgress,
  saveProgress,
  onSynthesisFinished,
  onSynthesisProgress,
  isTauriAvailable,
  previewNarration as fetchNarrationPreview,
} from "../lib/tauri";
import {
  type RecentDocument,
  getRecentDocuments,
  saveRecentDocument,
  clearRecentDocuments,
} from "../lib/history";

// ── Types ────────────────────────────────────────────────────────────

export type AppPhase =
  | "idle"
  | "selected"
  | "synthesizing"
  | "ready"
  | "error";

export interface PlayerState {
  isPlaying: boolean;
  segment: number;
  globalPosition: number;
  totalDuration: number;
  playbackRate: number;
  hasError: boolean;
  errorMessage: string;
  statusMessage: string;
  canRetry: boolean;
  canSkip: boolean;
}

// ── Hook ─────────────────────────────────────────────────────────────

export function useSonara() {
  const [phase, setPhase] = useState<AppPhase>("idle");
  const [documentName, setDocumentName] = useState("");
  const [statusText, setStatusText] = useState("Your file stays on this device.");
  const [errorText, setErrorText] = useState("");
  const [session, setSession] = useState<FrontendSession | null>(null);
  const [tauriReady, setTauriReady] = useState(false);
  const [recentDocs, setRecentDocs] = useState<RecentDocument[]>(() => getRecentDocuments());

  // Voice selection state
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [speechEngine, setSpeechEngine] = useState<SpeechEngine>(() => {
    try { return localStorage.getItem("sonara_speech_engine") === "kokoro" ? "kokoro" : "piper"; } catch { return "piper"; }
  });
  const [resourceProfile, setResourceProfile] = useState<ResourceProfile>(() => {
    try {
      const value = localStorage.getItem("sonara_resource_profile");
      return value === "low_resource" || value === "high_performance" ? value : "standard";
    } catch { return "standard"; }
  });
  const handleResourceProfileChange = useCallback((value: ResourceProfile) => {
    setResourceProfile(value);
    try { localStorage.setItem("sonara_resource_profile", value); } catch { /* storage may be unavailable */ }
  }, []);
  const [selectedVoice, setSelectedVoice] = useState<string>(() => {
    try {
      const selected = localStorage.getItem("sonara_selected_voice");
      if (localStorage.getItem("sonara_speech_engine") === "kokoro") {
        return selected?.startsWith("af_") || selected?.startsWith("am_") ? selected : "af_sarah";
      }
      return selected && !selected.startsWith("af_") && !selected.startsWith("am_") ? selected : "en_US-ryan-medium";
    } catch {
      return "en_US-ryan-medium";
    }
  });

  const handleVoiceChange = useCallback((voiceId: string) => {
    setSelectedVoice(voiceId);
    try {
      localStorage.setItem("sonara_selected_voice", voiceId);
    } catch {
      // storage unavailable
    }
  }, []);

  const handleSpeechEngineChange = useCallback((value: SpeechEngine) => {
    setSpeechEngine(value);
    try { localStorage.setItem("sonara_speech_engine", value); } catch { /* storage unavailable */ }
    handleVoiceChange(value === "kokoro" ? "af_sarah" : "en_US-ryan-medium");
  }, [handleVoiceChange]);

  const [piperVariation, setPiperVariation] = useState<PiperVariation>(() => {
    try {
      const stored = localStorage.getItem("sonara_piper_variation");
      return stored === "less" || stored === "more" ? stored : "voice_default";
    } catch {
      return "voice_default";
    }
  });
  const handlePiperVariationChange = useCallback((value: PiperVariation) => {
    setPiperVariation(value);
    try {
      localStorage.setItem("sonara_piper_variation", value);
    } catch {
      // Storage may be unavailable in restricted WebViews.
    }
  }, []);
  const [expandDates, setExpandDates] = useState(() => {
    try { return localStorage.getItem("sonara_expand_dates") === "true"; } catch { return false; }
  });
  const [expandCitations, setExpandCitations] = useState(() => {
    try { return localStorage.getItem("sonara_expand_citations") === "true"; } catch { return false; }
  });
  const handleExpandDatesChange = useCallback((enabled: boolean) => {
    setExpandDates(enabled);
    try { localStorage.setItem("sonara_expand_dates", String(enabled)); } catch { /* storage unavailable */ }
  }, []);
  const handleExpandCitationsChange = useCallback((enabled: boolean) => {
    setExpandCitations(enabled);
    try { localStorage.setItem("sonara_expand_citations", String(enabled)); } catch { /* storage unavailable */ }
  }, []);

  // Modals state
  const [isShortcutsOpen, setIsShortcutsOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isAssistantOpen, setIsAssistantOpen] = useState(false);

  // Player state
  const [playerState, setPlayerState] = useState<PlayerState>({
    isPlaying: false,
    segment: 0,
    globalPosition: 0,
    totalDuration: 0,
    playbackRate: 1.0,
    hasError: false,
    errorMessage: "",
    statusMessage: "Ready to play.",
    canRetry: false,
    canSkip: false,
  });

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const segmentRef = useRef(0);
  const expectedSourceRef = useRef("");
  const pendingOffsetRef = useRef(0);
  const pendingAutoplayRef = useRef(false);
  const isPlayingRef = useRef(false);
  const hasErrorRef = useRef(false);
  const resumeAfterErrorRef = useRef(false);
  const sessionRef = useRef<FrontendSession | null>(null);
  const startsRef = useRef<number[]>([]);
  const totalDurationRef = useRef(0);

  // Narration pause state
  const narrationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const narrationDeadlineRef = useRef(0);
  const narrationRemainingRef = useRef(0);
  const inNarrationPauseRef = useRef(false);

  // Progress save throttle
  const progressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const audioLoadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Helpers ──────────────────────────────────────────────────────

  const updatePlayerState = useCallback((patch: Partial<PlayerState>) => {
    setPlayerState((prev) => ({ ...prev, ...patch }));
  }, []);

  const clearNarrationPause = useCallback(() => {
    if (narrationTimerRef.current !== null) clearTimeout(narrationTimerRef.current);
    narrationTimerRef.current = null;
    inNarrationPauseRef.current = false;
    narrationRemainingRef.current = 0;
  }, []);

  const isExpectedAudioSource = useCallback(() => {
    const audio = audioRef.current;
    if (!audio?.currentSrc) return true;
    try {
      return new URL(audio.currentSrc).pathname === new URL(expectedSourceRef.current).pathname;
    } catch {
      return audio.currentSrc === expectedSourceRef.current;
    }
  }, []);

  const mediaDiagnostics = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return "no audio element";
    const error = audio.error;
    return `readyState=${audio.readyState}, networkState=${audio.networkState}` +
      (error ? `, mediaError=${error.code}${error.message ? ` (${error.message})` : ""}` : "");
  }, []);

  // ── Progress ────────────────────────────────────────────────────

  const persistProgress = useCallback(async (index?: number, offset?: number) => {
    const s = sessionRef.current;
    if (!s) return;
    const seg = index ?? segmentRef.current;
    const off = offset ?? (audioRef.current?.currentTime || 0);
    const progress: Progress = {
      version: 1,
      sourceSha256: s.sourceSha256,
      segment: seg,
      offsetSeconds: Math.max(0, off),
      playbackRate: Number(audioRef.current?.playbackRate || 1),
    };
    try {
      await saveProgress(progress);
    } catch {
      updatePlayerState({ statusMessage: "Progress could not be saved." });
    }
  }, [updatePlayerState]);

  const scheduleProgressSave = useCallback(() => {
    if (progressTimerRef.current !== null) return;
    progressTimerRef.current = setTimeout(() => {
      progressTimerRef.current = null;
      void persistProgress();
    }, 1000);
  }, [persistProgress]);

  // ── Rendering ───────────────────────────────────────────────────

  const renderPosition = useCallback((position?: number) => {
    const audio = audioRef.current;
    const pos = position ?? ((startsRef.current[segmentRef.current] || 0) + (audio?.currentTime || 0));
    const bounded = Math.max(0, Math.min(totalDurationRef.current, pos));
    updatePlayerState({ globalPosition: bounded });
  }, [updatePlayerState]);

  // ── Audio Error ─────────────────────────────────────────────────

  const showAudioError = useCallback((reason?: string) => {
    if (audioLoadTimerRef.current !== null) clearTimeout(audioLoadTimerRef.current);
    audioLoadTimerRef.current = null;
    resumeAfterErrorRef.current = isPlayingRef.current || pendingAutoplayRef.current;
    pendingAutoplayRef.current = false;
    hasErrorRef.current = true;
    isPlayingRef.current = false;
    const audio = audioRef.current;
    const mediaError = audio?.error;
    const errorDetail = reason || (mediaError
      ? `Media error ${mediaError.code}${mediaError.message ? `: ${mediaError.message}` : ""}.`
      : `The WebView could not load the local audio resource (${mediaDiagnostics()}).`);
    const s = sessionRef.current;
    updatePlayerState({
      isPlaying: false,
      hasError: true,
      errorMessage: `${errorDetail} Retry this passage or skip it.`,
      statusMessage: `${errorDetail} Retry this passage or skip it.`,
      canRetry: true,
      canSkip: s ? segmentRef.current < s.chunks.length - 1 : false,
    });
  }, [mediaDiagnostics, updatePlayerState]);

  // ── Load Chunk ──────────────────────────────────────────────────

  const loadChunk = useCallback((index: number, offset = 0, autoplay = false) => {
    clearNarrationPause();
    if (audioLoadTimerRef.current !== null) clearTimeout(audioLoadTimerRef.current);
    audioLoadTimerRef.current = null;
    const s = sessionRef.current;
    if (!s || index < 0 || index >= s.chunks.length) {
      isPlayingRef.current = false;
      updatePlayerState({ isPlaying: false });
      return;
    }
    segmentRef.current = index;
    pendingOffsetRef.current = Math.max(0, offset || 0);
    pendingAutoplayRef.current = autoplay;
    hasErrorRef.current = false;
    resumeAfterErrorRef.current = false;
    isPlayingRef.current = false;

    const audio = audioRef.current;
    if (!audio) return;
    audio.pause();
    expectedSourceRef.current = `${s.audioBaseUrl}/${s.sourceSha256}/${index}`;
    audio.src = expectedSourceRef.current;
    audio.load();

    updatePlayerState({
      isPlaying: false,
      segment: index,
      hasError: false,
      errorMessage: "",
      canRetry: false,
      canSkip: false,
      statusMessage: `Loading passage ${index + 1} of ${s.chunks.length}…`,
    });
    renderPosition((startsRef.current[index] || 0) + pendingOffsetRef.current);

    audioLoadTimerRef.current = setTimeout(() => {
      if (audio.readyState < HTMLMediaElement.HAVE_METADATA && isExpectedAudioSource()) {
        showAudioError(`The local audio did not load within 12 seconds (${mediaDiagnostics()}).`);
      }
    }, 12_000);
  }, [clearNarrationPause, isExpectedAudioSource, mediaDiagnostics, renderPosition, showAudioError, updatePlayerState]);

  // ── Playback ────────────────────────────────────────────────────

  const startPlayback = useCallback(async () => {
    const s = sessionRef.current;
    const audio = audioRef.current;
    if (!s?.chunks?.length || !audio) return;

    if (hasErrorRef.current) {
      updatePlayerState({ statusMessage: "Retry this passage or skip it to continue." });
      return;
    }

    if (inNarrationPauseRef.current) {
      const wait = narrationRemainingRef.current;
      narrationDeadlineRef.current = Date.now() + wait;
      narrationTimerRef.current = setTimeout(() => {
        narrationTimerRef.current = null;
        inNarrationPauseRef.current = false;
        loadChunk(segmentRef.current + 1, 0, true);
      }, wait);
      isPlayingRef.current = true;
      updatePlayerState({ isPlaying: true, statusMessage: "Resuming the pause between passages…" });
      return;
    }

    if (audio.ended) {
      loadChunk(0, 0, true);
      return;
    }

    try {
      updatePlayerState({ statusMessage: "Starting audio…" });
      let timeoutId: ReturnType<typeof setTimeout>;
      try {
        await Promise.race([
          audio.play(),
          new Promise((_, reject) => {
            timeoutId = setTimeout(() => reject(new Error(
              `Playback did not start within 5 seconds (${mediaDiagnostics()}).`
            )), 5_000);
          }),
        ]);
      } finally {
        clearTimeout(timeoutId!);
      }
      isPlayingRef.current = true;
      updatePlayerState({
        isPlaying: true,
        statusMessage: `Playing passage ${segmentRef.current + 1} of ${s.chunks.length}.`,
      });
    } catch (error: unknown) {
      isPlayingRef.current = false;
      updatePlayerState({ isPlaying: false });
      const err = error as { name?: string; message?: string };
      if (err?.name === "NotAllowedError") {
        updatePlayerState({
          statusMessage: "The WebView blocked playback. Click Play again, then check the system output volume.",
        });
      } else {
        const detail = err?.message || String(error);
        updatePlayerState({
          statusMessage: `Playback could not start: ${detail}`,
          hasError: true,
        });
      }
    }
  }, [loadChunk, mediaDiagnostics, updatePlayerState]);

  const pausePlayback = useCallback(() => {
    if (narrationTimerRef.current !== null) {
      clearTimeout(narrationTimerRef.current);
      narrationTimerRef.current = null;
      narrationRemainingRef.current = Math.max(0, narrationDeadlineRef.current - Date.now());
      inNarrationPauseRef.current = true;
    } else {
      audioRef.current?.pause();
    }
    isPlayingRef.current = false;
    updatePlayerState({ isPlaying: false, statusMessage: "Paused." });
    void persistProgress();
  }, [persistProgress, updatePlayerState]);

  // ── Seek ────────────────────────────────────────────────────────

  const seekTo = useCallback((position: number, resume = isPlayingRef.current) => {
    const s = sessionRef.current;
    if (!s) return;
    position = Math.max(0, Math.min(totalDurationRef.current, position));
    let nextIndex = s.chunks.length - 1;
    let offset = s.chunks[nextIndex].durationSeconds;
    for (let i = 0; i < s.chunks.length; i++) {
      if (position < (startsRef.current[i] || 0) + s.chunks[i].durationSeconds || i === s.chunks.length - 1) {
        nextIndex = i;
        offset = Math.max(0, position - (startsRef.current[i] || 0));
        break;
      }
    }
    loadChunk(nextIndex, offset, resume);
    void persistProgress(nextIndex, offset);
  }, [loadChunk, persistProgress]);

  const seekToChunk = useCallback((chunkIndex: number) => {
    const s = sessionRef.current;
    if (!s || chunkIndex < 0 || chunkIndex >= s.chunks.length) return;
    loadChunk(chunkIndex, 0, isPlayingRef.current);
    void persistProgress(chunkIndex, 0);
  }, [loadChunk, persistProgress]);

  const seekRelative = useCallback((deltaSeconds: number) => {
    const current = (startsRef.current[segmentRef.current] || 0) + (audioRef.current?.currentTime || 0);
    seekTo(current + deltaSeconds);
  }, [seekTo]);

  // ── Speed ───────────────────────────────────────────────────────

  const setSpeed = useCallback((rate: number, save = true) => {
    const clamped = Math.max(0.7, Math.min(1.5, Math.round(rate * 10) / 10));
    const audio = audioRef.current;
    if (audio) audio.playbackRate = clamped;
    updatePlayerState({ playbackRate: clamped });
    if (save) scheduleProgressSave();
  }, [scheduleProgressSave, updatePlayerState]);

  const adjustSpeed = useCallback((delta: number) => {
    setSpeed(playerState.playbackRate + delta);
  }, [playerState.playbackRate, setSpeed]);

  // ── Retry / Skip ────────────────────────────────────────────────

  const retryPassage = useCallback(() => {
    loadChunk(segmentRef.current, pendingOffsetRef.current, resumeAfterErrorRef.current);
  }, [loadChunk]);

  const skipPassage = useCallback(() => {
    loadChunk(segmentRef.current + 1, 0, resumeAfterErrorRef.current);
  }, [loadChunk]);

  // ── Show Session ────────────────────────────────────────────────

  const showSession = useCallback(async (nextSession: FrontendSession) => {
    sessionRef.current = nextSession;
    setSession(nextSession);
    const starts: number[] = [];
    let total = 0;
    for (const chunk of nextSession.chunks) {
      starts.push(total);
      total += chunk.durationSeconds;
    }
    startsRef.current = starts;
    totalDurationRef.current = total;

    setDocumentName(nextSession.sourceName);
    setStatusText(`Ready to listen · ${nextSession.chunks.length} passages · ${nextSession.voice}`);
    setPhase("ready");

    // Save to recent documents history
    const updatedHistory = saveRecentDocument({
      sourceName: nextSession.sourceName,
      sourceSha256: nextSession.sourceSha256,
      voice: nextSession.voice,
      chunksCount: nextSession.chunks.length,
      totalDurationSeconds: total,
    });
    setRecentDocs(updatedHistory);

    try {
      const saved = await loadProgress(nextSession.sourceSha256);
      const valid = saved &&
        saved.segment < nextSession.chunks.length &&
        saved.offsetSeconds <= nextSession.chunks[saved.segment].durationSeconds;
      const restoreIndex = valid ? saved.segment : 0;
      const restoreOffset = valid ? saved.offsetSeconds : 0;
      const rate = valid ? saved.playbackRate : 1;

      setSpeed(rate, false);
      loadChunk(restoreIndex, restoreOffset, false);
      renderPosition((starts[restoreIndex] || 0) + restoreOffset);
      updatePlayerState({
        totalDuration: total,
        statusMessage: valid ? "Reading progress restored." : "Ready to play.",
      });
    } catch {
      loadChunk(0, 0, false);
      updatePlayerState({
        totalDuration: total,
        statusMessage: "Could not restore reading progress.",
        hasError: true,
      });
    }
  }, [loadChunk, renderPosition, setSpeed, updatePlayerState]);

  // ── History ─────────────────────────────────────────────────────

  const handleClearHistory = useCallback(() => {
    clearRecentDocuments();
    setRecentDocs([]);
  }, []);

  // ── Document Picking ────────────────────────────────────────────

  const chooseDocument = useCallback(async () => {
    audioRef.current?.pause();
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
  }, []);

  const beginSynthesis = useCallback(async () => {
    audioRef.current?.pause();
    setPhase("synthesizing");
    setStatusText(`Preparing speech with the local ${speechEngine === "kokoro" ? "Kokoro" : "Piper"} voice…`);
    try {
      await startReading(selectedVoice, piperVariation, expandDates, expandCitations, speechEngine, resourceProfile);
    } catch (error) {
      setPhase("selected");
      setErrorText(String(error));
    }
  }, [selectedVoice, piperVariation, expandDates, expandCitations, speechEngine, resourceProfile]);

  const previewCurrentNarration = useCallback((): Promise<NarrationPreview> => {
    return fetchNarrationPreview(speechEngine === "kokoro" ? "en_US-ryan-medium" : selectedVoice, expandDates, expandCitations);
  }, [selectedVoice, expandDates, expandCitations, speechEngine]);

  const cancelSynthesis = useCallback(async () => {
    try {
      await cancelReading();
      setStatusText("Stopping the local speech worker…");
    } catch (error) {
      setStatusText(String(error));
    }
  }, []);

  // ── Audio Event Handlers ────────────────────────────────────────

  const handleLoadedMetadata = useCallback(async () => {
    if (!isExpectedAudioSource()) return;
    if (audioLoadTimerRef.current !== null) clearTimeout(audioLoadTimerRef.current);
    audioLoadTimerRef.current = null;
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = Math.min(pendingOffsetRef.current, Math.max(0, audio.duration - 0.02));
    audio.playbackRate = playerState.playbackRate;
    renderPosition();
    const s = sessionRef.current;
    updatePlayerState({
      statusMessage: `Ready · passage ${segmentRef.current + 1} of ${s?.chunks.length ?? 0}.`,
    });
    if (pendingAutoplayRef.current) {
      pendingAutoplayRef.current = false;
      await startPlayback();
    }
  }, [isExpectedAudioSource, playerState.playbackRate, renderPosition, startPlayback, updatePlayerState]);

  const handleTimeUpdate = useCallback(() => {
    renderPosition();
    scheduleProgressSave();
  }, [renderPosition, scheduleProgressSave]);

  const handleError = useCallback(() => {
    if (isExpectedAudioSource()) showAudioError();
  }, [isExpectedAudioSource, showAudioError]);

  const handlePlaying = useCallback(() => {
    isPlayingRef.current = true;
    const s = sessionRef.current;
    updatePlayerState({
      isPlaying: true,
      statusMessage: `Playing passage ${segmentRef.current + 1} of ${s?.chunks.length ?? 0}.`,
    });
  }, [updatePlayerState]);

  const handleEnded = useCallback(() => {
    if (!isExpectedAudioSource()) return;
    const audio = audioRef.current;
    void persistProgress(segmentRef.current, audio?.duration ?? 0);
    isPlayingRef.current = false;
    updatePlayerState({ isPlaying: false });
    const s = sessionRef.current;
    if (!s) return;
    if (segmentRef.current >= s.chunks.length - 1) {
      updatePlayerState({ statusMessage: "You have reached the end of this document." });
      return;
    }
    const delay = Math.max(0, s.chunks[segmentRef.current].pauseAfterMs || 0);
    if (delay > 0) {
      narrationRemainingRef.current = delay;
      inNarrationPauseRef.current = true;
      narrationDeadlineRef.current = Date.now() + delay;
      updatePlayerState({ statusMessage: "Pause between passages…" });
      narrationTimerRef.current = setTimeout(() => {
        narrationTimerRef.current = null;
        inNarrationPauseRef.current = false;
        loadChunk(segmentRef.current + 1, 0, true);
      }, delay);
    } else {
      loadChunk(segmentRef.current + 1, 0, true);
    }
  }, [isExpectedAudioSource, loadChunk, persistProgress, updatePlayerState]);

  const handleCanPlay = useCallback(() => {
    if (isExpectedAudioSource() && !isPlayingRef.current) {
      updatePlayerState({
        statusMessage: `Audio loaded · passage ${segmentRef.current + 1} is ready.`,
      });
    }
  }, [isExpectedAudioSource, updatePlayerState]);

  const handleWaiting = useCallback(() => {
    if (isExpectedAudioSource()) {
      updatePlayerState({ statusMessage: "Waiting for the local audio passage to load…" });
    }
  }, [isExpectedAudioSource, updatePlayerState]);

  // ── Global Keyboard Shortcuts ───────────────────────────────────

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger shortcuts if focus is in an input or textarea
      const target = e.target as HTMLElement | null;
      if (target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.isContentEditable) {
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

      if (e.key === "Escape") {
        if (isShortcutsOpen) setIsShortcutsOpen(false);
        if (isSettingsOpen) setIsSettingsOpen(false);
        if (isHistoryOpen) setIsHistoryOpen(false);
        if (isAssistantOpen) setIsAssistantOpen(false);
        return;
      }

      // Media shortcuts require a ready session
      if (phase !== "ready" || !sessionRef.current) return;

      if (e.key === " " || e.key === "k" || e.key === "K") {
        e.preventDefault();
        if (isPlayingRef.current) {
          pausePlayback();
        } else {
          void startPlayback();
        }
      } else if (e.key === "ArrowLeft" || e.key === "j" || e.key === "J") {
        e.preventDefault();
        seekRelative(-5);
      } else if (e.key === "ArrowRight" || e.key === "l" || e.key === "L") {
        e.preventDefault();
        seekRelative(5);
      } else if (e.key === "ArrowUp" || e.key === "]") {
        e.preventDefault();
        adjustSpeed(0.1);
      } else if (e.key === "ArrowDown" || e.key === "[") {
        e.preventDefault();
        adjustSpeed(-0.1);
      } else if (e.key === "Home") {
        e.preventDefault();
        seekTo(0);
      } else if (e.key === "End") {
        e.preventDefault();
        seekTo(totalDurationRef.current);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    phase,
    isShortcutsOpen,
    isSettingsOpen,
    isHistoryOpen,
    pausePlayback,
    startPlayback,
    seekRelative,
    seekTo,
    adjustSpeed,
  ]);

  // ── Initialize ──────────────────────────────────────────────────

  useEffect(() => {
    if (!isTauriAvailable()) {
      setErrorText("Sonara desktop APIs are unavailable. Start the application through Tauri.");
      return;
    }
    setTauriReady(true);

    let unlistenFn: (() => void) | null = null;
    let unlistenProgressFn: (() => void) | null = null;

    const init = async () => {
      try {
        unlistenFn = await onSynthesisFinished(async (payload) => {
          if ("Ok" in payload.result) {
            setPhase("ready");
            await showSession(payload.result.Ok);
          } else {
            setPhase("selected");
            setErrorText(payload.result.Err || "Speech generation failed.");
          }
        });
      } catch {
        /* event listener unavailable */
      }

      try {
        unlistenProgressFn = await onSynthesisProgress((payload) => {
          const total = payload.totalChunks;
          const current = payload.completedChunks;
          const pct = total > 0 ? Math.round((current / total) * 100) : 0;
          setStatusText(`Synthesizing speech: passage ${current} of ${total} (${pct}%)…`);
        });
      } catch {
        /* progress listener unavailable */
      }

      try {
        const availableVoices = await listVoices();
        setVoices(availableVoices);
        const savedVoice = localStorage.getItem("sonara_selected_voice");
        if (!savedVoice || !availableVoices.some((v) => v.id === savedVoice)) {
          const defaultVoice = availableVoices.find((v) => v.isDefault)?.id || availableVoices[0]?.id || "en_US-ryan-medium";
          setSelectedVoice(defaultVoice);
        }
      } catch {
        /* voices unavailable */
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
  }, [showSession]);

  return {
    // State
    phase,
    documentName,
    statusText,
    errorText,
    session,
    playerState,
    tauriReady,
    audioRef,
    chunkStarts: startsRef.current,
    recentDocs,

    // Voice
    voices,
    speechEngine,
    setSpeechEngine: handleSpeechEngineChange,
    resourceProfile,
    setResourceProfile: handleResourceProfileChange,
    selectedVoice,
    setSelectedVoice: handleVoiceChange,
    piperVariation,
    setPiperVariation: handlePiperVariationChange,
    expandDates,
    setExpandDates: handleExpandDatesChange,
    expandCitations,
    setExpandCitations: handleExpandCitationsChange,
    previewCurrentNarration,
    selectedVoiceName: voices.find((v) => v.id === selectedVoice)?.name ?? selectedVoice,

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
    beginSynthesis,
    cancelSynthesis,
    startPlayback,
    pausePlayback,
    seekTo,
    seekToChunk,
    seekRelative,
    setSpeed,
    retryPassage,
    skipPassage,
    clearHistory: handleClearHistory,

    // Audio event handlers
    handleLoadedMetadata,
    handleTimeUpdate,
    handleError,
    handlePlaying,
    handleEnded,
    handleCanPlay,
    handleWaiting,
  };
}

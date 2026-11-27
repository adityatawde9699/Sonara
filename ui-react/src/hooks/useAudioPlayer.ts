import { useCallback, useRef, useState } from "react";
import { type FrontendSession, type Progress, PROGRESS_VERSION, loadProgress, resolveProgressSegment, saveProgress } from "../lib/tauri";

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

const INITIAL_PLAYER_STATE: PlayerState = {
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
};

const AUDIO_LOAD_TIMEOUT_MS = 12_000;
const PLAY_START_TIMEOUT_MS = 5_000;
const PROGRESS_SAVE_INTERVAL_MS = 1_000;

/** Start time of each passage, in seconds from the start of the document. */
export function getChunkStarts(chunks: FrontendSession["chunks"]): number[] {
  const starts: number[] = [];
  let total = 0;
  for (const chunk of chunks) {
    starts.push(total);
    total += chunk.durationSeconds;
  }
  return starts;
}

export function sessionDuration(session: FrontendSession): number {
  return session.chunks.reduce((total, chunk) => total + chunk.durationSeconds, 0);
}

/**
 * Plays a session's passages one after another through a single audio
 * element, with the planned pause between passages, seeking across passage
 * boundaries, and throttled progress saving.
 *
 * Playback state that event handlers read synchronously lives in refs; the
 * rendered state is mirrored into `playerState`.
 */
export function useAudioPlayer() {
  const [playerState, setPlayerState] = useState<PlayerState>(INITIAL_PLAYER_STATE);

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

  // The pause between passages runs on a timer so it can be paused too.
  const narrationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const narrationDeadlineRef = useRef(0);
  const narrationRemainingRef = useRef(0);
  const inNarrationPauseRef = useRef(false);

  const progressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const audioLoadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // A passage requested before the <audio> element mounted. The player mounts
  // in the same render that shows a new session, and restoring progress can
  // finish first; the load then runs as soon as the element attaches.
  const pendingLoadRef = useRef<{ index: number; offset: number; autoplay: boolean } | null>(null);

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

  const clearLoadTimer = useCallback(() => {
    if (audioLoadTimerRef.current !== null) clearTimeout(audioLoadTimerRef.current);
    audioLoadTimerRef.current = null;
  }, []);

  /** Media events from a previous `src` arrive late; ignore them. */
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
    const segment = index ?? segmentRef.current;
    const progress: Progress = {
      version: PROGRESS_VERSION,
      sourceSha256: s.sourceSha256,
      segment,
      offsetSeconds: Math.max(0, offset ?? (audioRef.current?.currentTime || 0)),
      playbackRate: Number(audioRef.current?.playbackRate || 1),
      unitId: s.chunks[segment]?.unitId ?? null,
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
    }, PROGRESS_SAVE_INTERVAL_MS);
  }, [persistProgress]);

  const renderPosition = useCallback((position?: number) => {
    const audio = audioRef.current;
    const pos = position ?? ((startsRef.current[segmentRef.current] || 0) + (audio?.currentTime || 0));
    updatePlayerState({ globalPosition: Math.max(0, Math.min(totalDurationRef.current, pos)) });
  }, [updatePlayerState]);

  const showAudioError = useCallback((reason?: string) => {
    clearLoadTimer();
    resumeAfterErrorRef.current = isPlayingRef.current || pendingAutoplayRef.current;
    pendingAutoplayRef.current = false;
    hasErrorRef.current = true;
    isPlayingRef.current = false;
    const mediaError = audioRef.current?.error;
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
  }, [clearLoadTimer, mediaDiagnostics, updatePlayerState]);

  // ── Loading and playback ────────────────────────────────────────

  const loadChunk = useCallback((index: number, offset = 0, autoplay = false) => {
    clearNarrationPause();
    clearLoadTimer();
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
    if (!audio) {
      pendingLoadRef.current = { index, offset: pendingOffsetRef.current, autoplay };
      return;
    }
    pendingLoadRef.current = null;
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
    }, AUDIO_LOAD_TIMEOUT_MS);
  }, [clearLoadTimer, clearNarrationPause, isExpectedAudioSource, mediaDiagnostics, renderPosition, showAudioError, updatePlayerState]);

  /** Ref callback for the player's <audio> element. */
  const attachAudio = useCallback((element: HTMLAudioElement | null) => {
    audioRef.current = element;
    const pending = pendingLoadRef.current;
    if (element && pending) {
      pendingLoadRef.current = null;
      loadChunk(pending.index, pending.offset, pending.autoplay);
    }
  }, [loadChunk]);

  /** Wait `delay` ms (the planned pause), then play the next passage. */
  const scheduleNextPassage = useCallback((delay: number) => {
    narrationRemainingRef.current = delay;
    inNarrationPauseRef.current = true;
    narrationDeadlineRef.current = Date.now() + delay;
    narrationTimerRef.current = setTimeout(() => {
      narrationTimerRef.current = null;
      inNarrationPauseRef.current = false;
      loadChunk(segmentRef.current + 1, 0, true);
    }, delay);
  }, [loadChunk]);

  const startPlayback = useCallback(async () => {
    const s = sessionRef.current;
    const audio = audioRef.current;
    if (!s?.chunks?.length || !audio) return;

    if (hasErrorRef.current) {
      updatePlayerState({ statusMessage: "Retry this passage or skip it to continue." });
      return;
    }

    if (inNarrationPauseRef.current) {
      scheduleNextPassage(narrationRemainingRef.current);
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
      let timeoutId: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([
          audio.play(),
          new Promise((_, reject) => {
            timeoutId = setTimeout(() => reject(new Error(
              `Playback did not start within 5 seconds (${mediaDiagnostics()}).`
            )), PLAY_START_TIMEOUT_MS);
          }),
        ]);
      } finally {
        clearTimeout(timeoutId);
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
        updatePlayerState({
          statusMessage: `Playback could not start: ${err?.message || String(error)}`,
          hasError: true,
        });
      }
    }
  }, [loadChunk, mediaDiagnostics, scheduleNextPassage, updatePlayerState]);

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

  const togglePlayback = useCallback(() => {
    if (isPlayingRef.current) {
      pausePlayback();
    } else {
      void startPlayback();
    }
  }, [pausePlayback, startPlayback]);

  /** Stop audio without changing the saved position (a new document is coming). */
  const suspend = useCallback(() => {
    audioRef.current?.pause();
  }, []);

  // ── Seeking ─────────────────────────────────────────────────────

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

  /** Jump to the start of a passage; keeps playing if it was, or starts when `autoplay`. */
  const seekToChunk = useCallback((chunkIndex: number, autoplay?: boolean) => {
    const s = sessionRef.current;
    if (!s || chunkIndex < 0 || chunkIndex >= s.chunks.length) return;
    loadChunk(chunkIndex, 0, autoplay ?? isPlayingRef.current);
    void persistProgress(chunkIndex, 0);
  }, [loadChunk, persistProgress]);

  const seekRelative = useCallback((deltaSeconds: number) => {
    const current = (startsRef.current[segmentRef.current] || 0) + (audioRef.current?.currentTime || 0);
    seekTo(current + deltaSeconds);
  }, [seekTo]);

  const seekToEnd = useCallback(() => {
    seekTo(totalDurationRef.current);
  }, [seekTo]);

  // ── Speed, retry and skip ───────────────────────────────────────

  const setSpeed = useCallback((rate: number, save = true) => {
    const clamped = Math.max(0.7, Math.min(1.5, Math.round(rate * 10) / 10));
    if (audioRef.current) audioRef.current.playbackRate = clamped;
    updatePlayerState({ playbackRate: clamped });
    if (save) scheduleProgressSave();
  }, [scheduleProgressSave, updatePlayerState]);

  const adjustSpeed = useCallback((delta: number) => {
    setSpeed(playerState.playbackRate + delta);
  }, [playerState.playbackRate, setSpeed]);

  const retryPassage = useCallback(() => {
    loadChunk(segmentRef.current, pendingOffsetRef.current, resumeAfterErrorRef.current);
  }, [loadChunk]);

  const skipPassage = useCallback(() => {
    loadChunk(segmentRef.current + 1, 0, resumeAfterErrorRef.current);
  }, [loadChunk]);

  // ── Sessions ────────────────────────────────────────────────────

  /** Switch to a new session and restore its saved position and speed. */
  const openSession = useCallback(async (nextSession: FrontendSession) => {
    sessionRef.current = nextSession;
    const starts = getChunkStarts(nextSession.chunks);
    const total = sessionDuration(nextSession);
    startsRef.current = starts;
    totalDurationRef.current = total;
    try {
      const saved = await loadProgress(nextSession.sourceSha256);
      const savedIndex = saved ? resolveProgressSegment(saved, nextSession.chunks) : -1;
      const valid = saved && savedIndex >= 0 &&
        saved.offsetSeconds <= nextSession.chunks[savedIndex].durationSeconds;
      const restoreIndex = valid ? savedIndex : 0;
      const restoreOffset = valid ? saved.offsetSeconds : 0;
      setSpeed(valid ? saved.playbackRate : 1, false);
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

  // ── Media element events ────────────────────────────────────────

  const handleLoadedMetadata = useCallback(async () => {
    if (!isExpectedAudioSource()) return;
    clearLoadTimer();
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = Math.min(pendingOffsetRef.current, Math.max(0, audio.duration - 0.02));
    audio.playbackRate = playerState.playbackRate;
    renderPosition();
    updatePlayerState({
      statusMessage: `Ready · passage ${segmentRef.current + 1} of ${sessionRef.current?.chunks.length ?? 0}.`,
    });
    if (pendingAutoplayRef.current) {
      pendingAutoplayRef.current = false;
      await startPlayback();
    }
  }, [clearLoadTimer, isExpectedAudioSource, playerState.playbackRate, renderPosition, startPlayback, updatePlayerState]);

  const handleTimeUpdate = useCallback(() => {
    renderPosition();
    scheduleProgressSave();
  }, [renderPosition, scheduleProgressSave]);

  const handleError = useCallback(() => {
    if (isExpectedAudioSource()) showAudioError();
  }, [isExpectedAudioSource, showAudioError]);

  const handlePlaying = useCallback(() => {
    isPlayingRef.current = true;
    updatePlayerState({
      isPlaying: true,
      statusMessage: `Playing passage ${segmentRef.current + 1} of ${sessionRef.current?.chunks.length ?? 0}.`,
    });
  }, [updatePlayerState]);

  const handleEnded = useCallback(() => {
    if (!isExpectedAudioSource()) return;
    void persistProgress(segmentRef.current, audioRef.current?.duration ?? 0);
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
      updatePlayerState({ statusMessage: "Pause between passages…" });
      scheduleNextPassage(delay);
    } else {
      loadChunk(segmentRef.current + 1, 0, true);
    }
  }, [isExpectedAudioSource, loadChunk, persistProgress, scheduleNextPassage, updatePlayerState]);

  const handleCanPlay = useCallback(() => {
    if (isExpectedAudioSource() && !isPlayingRef.current) {
      updatePlayerState({ statusMessage: `Audio loaded · passage ${segmentRef.current + 1} is ready.` });
    }
  }, [isExpectedAudioSource, updatePlayerState]);

  const handleWaiting = useCallback(() => {
    if (isExpectedAudioSource()) {
      updatePlayerState({ statusMessage: "Waiting for the local audio passage to load…" });
    }
  }, [isExpectedAudioSource, updatePlayerState]);

  return {
    playerState,
    audioRef,
    attachAudio,
    openSession,
    suspend,
    startPlayback,
    pausePlayback,
    togglePlayback,
    seekTo,
    seekToChunk,
    seekRelative,
    seekToEnd,
    setSpeed,
    adjustSpeed,
    retryPassage,
    skipPassage,
    handleLoadedMetadata,
    handleTimeUpdate,
    handleError,
    handlePlaying,
    handleEnded,
    handleCanPlay,
    handleWaiting,
  };
}

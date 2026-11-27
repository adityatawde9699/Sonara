import { useCallback, useRef, useState } from "react";
import { type FrontendChunk, type FrontendSession, type Progress, PROGRESS_VERSION, loadProgress, resolveProgressSegment, saveProgress } from "../lib/tauri";

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
  /** Passages planned for the document; more than are ready while streaming. */
  expectedChunks: number;
  /** False while later passages are still being synthesized. */
  isComplete: boolean;
  /** Waiting for a passage that has not been synthesized yet. */
  isBuffering: boolean;
  /** `totalDuration` plus an estimate for passages not yet synthesized. */
  estimatedDuration: number;
}

/** A passage the player is waiting for, because it is not synthesized yet. */
interface PendingPassage {
  index: number;
  /** Wait for this narration unit (a restored position) rather than the index. */
  unitId: string | null;
  offset: number;
  autoplay: boolean;
  /** Restoring saved progress: fall back to the start if it never arrives. */
  restore: boolean;
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
  expectedChunks: 0,
  isComplete: true,
  isBuffering: false,
  estimatedDuration: 0,
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

/** Ready duration plus the average ready passage length for each passage to come. */
export function estimateDuration(readyDuration: number, readyChunks: number, expectedChunks: number): number {
  if (readyChunks <= 0 || expectedChunks <= readyChunks) return readyDuration;
  return readyDuration + (readyDuration / readyChunks) * (expectedChunks - readyChunks);
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
  // Streaming: passages arrive while synthesis runs.
  const expectedChunksRef = useRef(0);
  const completeRef = useRef(true);
  const waitRef = useRef<PendingPassage | null>(null);

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

  /** Passages planned: the ready ones, or more while synthesis runs. */
  const plannedChunks = useCallback(() => {
    const ready = sessionRef.current?.chunks.length ?? 0;
    return completeRef.current ? ready : Math.max(ready, expectedChunksRef.current);
  }, []);

  /** Recompute passage start times and durations after the session grew. */
  const refreshTotals = useCallback(() => {
    const s = sessionRef.current;
    if (!s) return;
    startsRef.current = getChunkStarts(s.chunks);
    totalDurationRef.current = sessionDuration(s);
    const planned = plannedChunks();
    updatePlayerState({
      totalDuration: totalDurationRef.current,
      expectedChunks: planned,
      isComplete: completeRef.current,
      estimatedDuration: estimateDuration(totalDurationRef.current, s.chunks.length, planned),
    });
  }, [plannedChunks, updatePlayerState]);

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
    // While waiting for a passage, keep the position saved before the wait.
    if (!s || waitRef.current) return;
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
      canSkip: s ? segmentRef.current < plannedChunks() - 1 : false,
    });
  }, [clearLoadTimer, mediaDiagnostics, plannedChunks, updatePlayerState]);

  // ── Loading and playback ────────────────────────────────────────

  /** Wait for a passage that is still being synthesized. */
  const waitForPassage = useCallback((pending: PendingPassage) => {
    clearNarrationPause();
    clearLoadTimer();
    audioRef.current?.pause();
    waitRef.current = pending;
    hasErrorRef.current = false;
    isPlayingRef.current = pending.autoplay;
    updatePlayerState({
      isPlaying: pending.autoplay,
      isBuffering: true,
      segment: pending.index,
      hasError: false,
      errorMessage: "",
      canRetry: false,
      canSkip: false,
      globalPosition: totalDurationRef.current,
      statusMessage: pending.restore
        ? `Preparing passage ${pending.index + 1} to continue where you left off…`
        : `Preparing passage ${pending.index + 1} of ${plannedChunks()}…`,
    });
  }, [clearLoadTimer, clearNarrationPause, plannedChunks, updatePlayerState]);

  const loadChunk = useCallback((index: number, offset = 0, autoplay = false) => {
    clearNarrationPause();
    clearLoadTimer();
    const s = sessionRef.current;
    if (s && index >= s.chunks.length && !completeRef.current) {
      waitForPassage({ index, unitId: null, offset, autoplay, restore: false });
      return;
    }
    if (!s || index < 0 || index >= s.chunks.length) {
      isPlayingRef.current = false;
      updatePlayerState({ isPlaying: false });
      return;
    }
    waitRef.current = null;
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
      isBuffering: false,
      statusMessage: `Loading passage ${index + 1} of ${plannedChunks()}…`,
    });
    renderPosition((startsRef.current[index] || 0) + pendingOffsetRef.current);

    audioLoadTimerRef.current = setTimeout(() => {
      if (audio.readyState < HTMLMediaElement.HAVE_METADATA && isExpectedAudioSource()) {
        showAudioError(`The local audio did not load within 12 seconds (${mediaDiagnostics()}).`);
      }
    }, AUDIO_LOAD_TIMEOUT_MS);
  }, [clearLoadTimer, clearNarrationPause, isExpectedAudioSource, mediaDiagnostics, plannedChunks, renderPosition, showAudioError, updatePlayerState, waitForPassage]);

  /** Load the passage being waited for, if it has arrived (or never will). */
  const resolveWait = useCallback(() => {
    const pending = waitRef.current;
    const s = sessionRef.current;
    if (!pending || !s) return;
    let index = -1;
    if (pending.unitId) {
      index = s.chunks.findIndex((chunk) => chunk.unitId === pending.unitId);
      // The unit is gone (the rules changed); once all passages exist, fall
      // back to the saved passage number.
      if (index < 0 && completeRef.current && pending.index < s.chunks.length) index = pending.index;
    } else if (pending.index < s.chunks.length) {
      index = pending.index;
    }
    if (index < 0) {
      if (!completeRef.current) return;
      waitRef.current = null;
      if (pending.restore && s.chunks.length) {
        loadChunk(0, 0, false);
        updatePlayerState({ statusMessage: "Ready to play." });
      } else {
        isPlayingRef.current = false;
        updatePlayerState({
          isPlaying: false,
          isBuffering: false,
          statusMessage: "You have reached the end of this document.",
        });
      }
      return;
    }
    const offset = pending.offset <= s.chunks[index].durationSeconds ? pending.offset : 0;
    waitRef.current = null;
    loadChunk(index, offset, pending.autoplay);
    if (pending.restore) updatePlayerState({ statusMessage: "Reading progress restored." });
  }, [loadChunk, updatePlayerState]);

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

    if (waitRef.current) {
      waitRef.current.autoplay = true;
      isPlayingRef.current = true;
      updatePlayerState({
        isPlaying: true,
        statusMessage: `Passage ${waitRef.current.index + 1} plays as soon as it is ready…`,
      });
      return;
    }

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
        statusMessage: `Playing passage ${segmentRef.current + 1} of ${plannedChunks()}.`,
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
  }, [loadChunk, mediaDiagnostics, plannedChunks, scheduleNextPassage, updatePlayerState]);

  const pausePlayback = useCallback(() => {
    if (waitRef.current) {
      waitRef.current.autoplay = false;
      isPlayingRef.current = false;
      updatePlayerState({ isPlaying: false, statusMessage: "Paused." });
      return;
    }
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
    if (!s || chunkIndex < 0 || chunkIndex >= plannedChunks()) return;
    loadChunk(chunkIndex, 0, autoplay ?? isPlayingRef.current);
    void persistProgress(chunkIndex, 0);
  }, [loadChunk, persistProgress, plannedChunks]);

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

  /**
   * Switch to a new session and restore its saved position and speed.
   * `expectedChunks` above the ready count opens a session that is still
   * being synthesized; `appendChunks` and `completeSession` extend it.
   */
  const openSession = useCallback(async (nextSession: FrontendSession, options: { expectedChunks?: number } = {}) => {
    sessionRef.current = nextSession;
    waitRef.current = null;
    expectedChunksRef.current = Math.max(options.expectedChunks ?? 0, nextSession.chunks.length);
    completeRef.current = expectedChunksRef.current <= nextSession.chunks.length;
    const starts = getChunkStarts(nextSession.chunks);
    const total = sessionDuration(nextSession);
    startsRef.current = starts;
    totalDurationRef.current = total;
    refreshTotals();
    try {
      const saved = await loadProgress(nextSession.sourceSha256);
      if (saved && !completeRef.current) {
        // A saved passage that is not synthesized yet: wait for it.
        const byUnit = saved.unitId
          ? nextSession.chunks.findIndex((chunk) => chunk.unitId === saved.unitId)
          : -1;
        const waiting = saved.unitId ? byUnit < 0 : saved.segment >= nextSession.chunks.length;
        if (waiting && saved.segment < expectedChunksRef.current) {
          setSpeed(saved.playbackRate, false);
          waitForPassage({
            index: saved.segment,
            unitId: saved.unitId ?? null,
            offset: saved.offsetSeconds,
            autoplay: false,
            restore: true,
          });
          return;
        }
      }
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
  }, [loadChunk, refreshTotals, renderPosition, setSpeed, updatePlayerState, waitForPassage]);

  /**
   * Add passages that finished synthesizing. Returns the grown session, or
   * null when `firstIndex` does not follow on from the passages already
   * here (an event was missed); the caller then resynchronizes.
   */
  const appendChunks = useCallback((firstIndex: number, chunks: FrontendChunk[], expectedChunks: number): FrontendSession | null => {
    const s = sessionRef.current;
    if (!s || firstIndex !== s.chunks.length) return null;
    const grown = { ...s, chunks: [...s.chunks, ...chunks] };
    sessionRef.current = grown;
    expectedChunksRef.current = Math.max(expectedChunks, grown.chunks.length);
    // Every planned passage is playable; the finished event only confirms it.
    if (grown.chunks.length >= expectedChunksRef.current) completeRef.current = true;
    refreshTotals();
    resolveWait();
    return grown;
  }, [refreshTotals, resolveWait]);

  /** Synthesis finished: the session is whole. */
  const completeSession = useCallback((finalSession: FrontendSession) => {
    sessionRef.current = finalSession;
    completeRef.current = true;
    expectedChunksRef.current = finalSession.chunks.length;
    refreshTotals();
    resolveWait();
  }, [refreshTotals, resolveWait]);

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
      statusMessage: `Ready · passage ${segmentRef.current + 1} of ${plannedChunks()}.`,
    });
    if (pendingAutoplayRef.current) {
      pendingAutoplayRef.current = false;
      await startPlayback();
    }
  }, [clearLoadTimer, isExpectedAudioSource, playerState.playbackRate, plannedChunks, renderPosition, startPlayback, updatePlayerState]);

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
      statusMessage: `Playing passage ${segmentRef.current + 1} of ${plannedChunks()}.`,
    });
  }, [plannedChunks, updatePlayerState]);

  const handleEnded = useCallback(() => {
    if (!isExpectedAudioSource()) return;
    void persistProgress(segmentRef.current, audioRef.current?.duration ?? 0);
    isPlayingRef.current = false;
    updatePlayerState({ isPlaying: false });
    const s = sessionRef.current;
    if (!s) return;
    if (completeRef.current && segmentRef.current >= s.chunks.length - 1) {
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
    appendChunks,
    completeSession,
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

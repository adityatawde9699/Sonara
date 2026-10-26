(() => {
  const invoke = window.__TAURI__?.core?.invoke;
  const listen = window.__TAURI__?.event?.listen;
  const $ = (id) => document.getElementById(id);
  const audio = $("audio");
  const chooseButton = $("choose-document");
  const cancelButton = $("cancel-synthesis");
  const synthesisArea = $("synthesis-area");
  const synthesisStatus = $("synthesis-status");
  const playerCard = $("player-card");
  const playerStatus = $("player-status");
  const playButton = $("play");
  const pauseButton = $("pause");
  const retryButton = $("retry");
  const skipButton = $("skip");
  const seek = $("seek");
  const speed = $("speed");

  let session = null;
  let starts = [];
  let totalDuration = 0;
  let segment = 0;
  let pendingOffset = 0;
  let pendingAutoplay = false;
  let expectedSource = "";
  let isPlaying = false;
  let hasError = false;
  let resumeAfterError = false;
  let narrationTimer = null;
  let narrationDeadline = 0;
  let narrationRemaining = 0;
  let inNarrationPause = false;
  let progressTimer = null;
  let audioLoadTimer = null;

  function mediaDiagnostics() {
    const error = audio.error;
    return `readyState=${audio.readyState}, networkState=${audio.networkState}` +
      (error ? `, mediaError=${error.code}${error.message ? ` (${error.message})` : ""}` : "");
  }

  function reportError(error) {
    const message = typeof error === "string" ? error : error?.message || String(error);
    if (playerCard.hidden) {
      $("document-detail").textContent = message;
      $("document-detail").classList.add("error");
    } else {
      playerStatus.textContent = message;
      playerStatus.classList.add("error");
    }
  }

  function status(message) {
    playerStatus.textContent = message;
    playerStatus.classList.remove("error");
  }

  function formatClock(seconds) {
    const value = Math.max(0, Math.floor(seconds || 0));
    return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
  }

  function globalPosition() {
    return (starts[segment] || 0) + (audio.currentTime || 0);
  }

  function renderPosition(position = globalPosition()) {
    const bounded = Math.max(0, Math.min(totalDuration, position));
    $("position-label").textContent = `${formatClock(bounded)} / ${formatClock(totalDuration)}`;
    seek.value = String(totalDuration ? Math.round((bounded / totalDuration) * 1000) : 0);
  }

  function setPlaying(value) {
    isPlaying = value;
    playButton.disabled = value || !session?.chunks?.length;
    pauseButton.disabled = !value;
  }

  function clearNarrationPause() {
    if (narrationTimer !== null) clearTimeout(narrationTimer);
    narrationTimer = null;
    inNarrationPause = false;
    narrationRemaining = 0;
  }

  async function persistProgress(index = segment, offset = audio.currentTime || 0) {
    if (!session) return;
    const progress = {
      version: 1,
      sourceSha256: session.sourceSha256,
      segment: index,
      offsetSeconds: Math.max(0, offset),
      playbackRate: Number(speed.value),
    };
    try {
      await invoke("save_progress", { progress });
    } catch (error) {
      status(`Progress could not be saved: ${error}`);
    }
  }

  function scheduleProgressSave() {
    if (progressTimer !== null) return;
    progressTimer = setTimeout(() => {
      progressTimer = null;
      void persistProgress();
    }, 1000);
  }

  function setSpeed(save = true) {
    audio.playbackRate = Number(speed.value);
    $("speed-label").textContent = `${audio.playbackRate.toFixed(1)}×`;
    if (save) scheduleProgressSave();
  }

  function showAudioError(reason = "") {
    if (audioLoadTimer !== null) clearTimeout(audioLoadTimer);
    audioLoadTimer = null;
    resumeAfterError = isPlaying || pendingAutoplay;
    pendingAutoplay = false;
    hasError = true;
    setPlaying(false);
    const mediaError = audio.error;
    const errorDetail = reason || (mediaError
      ? `Media error ${mediaError.code}${mediaError.message ? `: ${mediaError.message}` : ""}.`
      : `The WebView could not load the local audio resource (${mediaDiagnostics()}).`);
    status(`${errorDetail} Retry this passage or skip it.`);
    playerStatus.classList.add("error");
    retryButton.hidden = false;
    skipButton.hidden = segment >= session.chunks.length - 1;
  }

  function isExpectedAudioSource() {
    if (!audio.currentSrc) return true;
    try {
      // WebKit may normalize the media URL. Its token/hash/index path still
      // identifies this passage if only the origin representation changes.
      return new URL(audio.currentSrc).pathname === new URL(expectedSource).pathname;
    } catch {
      return audio.currentSrc === expectedSource;
    }
  }

  function loadChunk(index, offset = 0, autoplay = false) {
    clearNarrationPause();
    if (audioLoadTimer !== null) clearTimeout(audioLoadTimer);
    audioLoadTimer = null;
    if (!session || index < 0 || index >= session.chunks.length) {
      setPlaying(false);
      return;
    }
    segment = index;
    pendingOffset = Math.max(0, offset || 0);
    pendingAutoplay = autoplay;
    hasError = false;
    resumeAfterError = false;
    retryButton.hidden = true;
    skipButton.hidden = true;
    setPlaying(false);
    const chunk = session.chunks[index];
    audio.pause();
    expectedSource = `${session.audioBaseUrl}/${session.sourceSha256}/${index}`;
    audio.src = expectedSource;
    audio.load();
    status(`Loading passage ${index + 1} of ${session.chunks.length}…`);
    audioLoadTimer = setTimeout(() => {
      if (audio.readyState < HTMLMediaElement.HAVE_METADATA && isExpectedAudioSource()) {
        showAudioError(`The local audio did not load within 12 seconds (${mediaDiagnostics()}).`);
      }
    }, 12_000);
    renderPosition(starts[index] + pendingOffset);
  }

  async function startPlayback() {
    if (!session?.chunks?.length) return;
    if (hasError) {
      status("Retry this passage or skip it to continue.");
      return;
    }
    if (inNarrationPause) {
      const wait = narrationRemaining;
      narrationDeadline = Date.now() + wait;
      narrationTimer = setTimeout(() => {
        narrationTimer = null;
        inNarrationPause = false;
        loadChunk(segment + 1, 0, true);
      }, wait);
      setPlaying(true);
      status("Resuming the pause between passages…");
      return;
    }
    if (audio.ended) {
      loadChunk(0, 0, true);
      return;
    }
    try {
      status("Starting audio…");
      let timeoutId;
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
        clearTimeout(timeoutId);
      }
      setPlaying(true);
      status(`Playing passage ${segment + 1} of ${session.chunks.length}.`);
    } catch (error) {
      setPlaying(false);
      if (error?.name === "NotAllowedError") {
        status("The WebView blocked playback. Click Play again, then check the system output volume.");
      } else {
        const detail = error?.message || String(error);
        status(`Playback could not start: ${detail}`);
        playerStatus.classList.add("error");
      }
    }
  }

  function pausePlayback() {
    if (narrationTimer !== null) {
      clearTimeout(narrationTimer);
      narrationTimer = null;
      narrationRemaining = Math.max(0, narrationDeadline - Date.now());
      inNarrationPause = true;
    } else {
      audio.pause();
    }
    setPlaying(false);
    void persistProgress();
    status("Paused.");
  }

  function seekTo(position, resume = isPlaying) {
    position = Math.max(0, Math.min(totalDuration, position));
    let nextIndex = session.chunks.length - 1;
    let offset = session.chunks[nextIndex].durationSeconds;
    for (let index = 0; index < session.chunks.length; index += 1) {
      if (position < starts[index] + session.chunks[index].durationSeconds || index === session.chunks.length - 1) {
        nextIndex = index;
        offset = Math.max(0, position - starts[index]);
        break;
      }
    }
    loadChunk(nextIndex, offset, resume);
    void persistProgress(nextIndex, offset);
  }

  async function showSession(nextSession) {
    session = nextSession;
    starts = [];
    totalDuration = 0;
    for (const chunk of session.chunks) {
      starts.push(totalDuration);
      totalDuration += chunk.durationSeconds;
    }
    $("document-title").textContent = session.sourceName;
    $("document-detail").textContent = `Ready to listen · ${session.chunks.length} passages · ${session.voice}`;
    $("player-title").textContent = session.sourceName;
    $("voice-label").textContent = session.voice;
    playerCard.hidden = false;
    try {
      const saved = await invoke("load_progress", { sourceSha256: session.sourceSha256 });
      const valid = saved && saved.segment < session.chunks.length && saved.offsetSeconds <= session.chunks[saved.segment].durationSeconds;
      const restoreIndex = valid ? saved.segment : 0;
      const restoreOffset = valid ? saved.offsetSeconds : 0;
      speed.value = valid ? String(saved.playbackRate) : "1";
      setSpeed(false);
      loadChunk(restoreIndex, restoreOffset, false);
      renderPosition(starts[restoreIndex] + restoreOffset);
      status(valid ? "Reading progress restored." : "Ready to play.");
    } catch (error) {
      loadChunk(0, 0, false);
      reportError(`Could not restore reading progress: ${error}`);
    }
  }

  chooseButton.addEventListener("click", async () => {
    audio.pause();
    try {
      const selected = await invoke("pick_pdf");
      if (!selected) return;
      $("document-title").textContent = selected.displayName;
      $("document-detail").textContent = "Selected on this device · ready to prepare speech";
      $("document-detail").classList.remove("error");
      playerCard.hidden = true;
      status("Ready to prepare this document.");
      chooseButton.dataset.selected = "true";
      $("start-synthesis").hidden = false;
    } catch (error) {
      reportError(error);
    }
  });

  const startButton = $("start-synthesis");
  startButton.addEventListener("click", async () => {
    if (!chooseButton.dataset.selected) return;
    audio.pause();
    playerCard.hidden = true;
    synthesisArea.hidden = false;
    synthesisStatus.textContent = "Preparing speech with the local Piper voice…";
    chooseButton.disabled = true;
    try {
      await invoke("start_reading");
    } catch (error) {
      synthesisArea.hidden = true;
      chooseButton.disabled = false;
      reportError(error);
    }
  });

  cancelButton.addEventListener("click", async () => {
    try {
      await invoke("cancel_reading");
      synthesisStatus.textContent = "Stopping the local speech worker…";
    } catch (error) {
      synthesisStatus.textContent = String(error);
    }
  });
  playButton.addEventListener("click", () => void startPlayback());
  pauseButton.addEventListener("click", pausePlayback);
  retryButton.addEventListener("click", () => loadChunk(segment, pendingOffset, resumeAfterError));
  skipButton.addEventListener("click", () => loadChunk(segment + 1, 0, resumeAfterError));
  speed.addEventListener("input", () => setSpeed());
  seek.addEventListener("input", () => renderPosition((Number(seek.value) / 1000) * totalDuration));
  seek.addEventListener("change", () => seekTo((Number(seek.value) / 1000) * totalDuration, isPlaying));

  audio.addEventListener("loadedmetadata", async () => {
    if (!isExpectedAudioSource()) return;
    if (audioLoadTimer !== null) clearTimeout(audioLoadTimer);
    audioLoadTimer = null;
    audio.currentTime = Math.min(pendingOffset, Math.max(0, audio.duration - 0.02));
    setSpeed();
    renderPosition();
    status(`Ready · passage ${segment + 1} of ${session.chunks.length}.`);
    if (pendingAutoplay) {
      pendingAutoplay = false;
      await startPlayback();
    }
  });
  audio.addEventListener("timeupdate", () => {
    renderPosition();
    scheduleProgressSave();
  });
  audio.addEventListener("error", () => {
    if (isExpectedAudioSource()) showAudioError();
  });
  audio.addEventListener("loadstart", () => {
    if (isExpectedAudioSource()) status(`Requesting passage ${segment + 1}…`);
  });
  audio.addEventListener("canplay", () => {
    if (isExpectedAudioSource() && !isPlaying) status(`Audio loaded · passage ${segment + 1} is ready.`);
  });
  audio.addEventListener("playing", () => {
    setPlaying(true);
    status(`Playing passage ${segment + 1} of ${session.chunks.length}.`);
  });
  audio.addEventListener("waiting", () => {
    if (isExpectedAudioSource()) status("Waiting for the local audio passage to load…");
  });
  audio.addEventListener("ended", () => {
    if (!isExpectedAudioSource()) return;
    void persistProgress(segment, audio.duration);
    setPlaying(false);
    if (segment >= session.chunks.length - 1) {
      status("You have reached the end of this document.");
      return;
    }
    const delay = Math.max(0, session.chunks[segment].pauseAfterMs || 0);
    if (delay > 0) {
      narrationRemaining = delay;
      inNarrationPause = true;
      narrationDeadline = Date.now() + delay;
      status("Pause between passages…");
      narrationTimer = setTimeout(() => {
        narrationTimer = null;
        inNarrationPause = false;
        loadChunk(segment + 1, 0, true);
      }, delay);
    } else {
      loadChunk(segment + 1, 0, true);
    }
  });

  async function initialize() {
    if (!invoke || !listen) {
      reportError("Sonara desktop APIs are unavailable. Start the application through Tauri.");
      chooseButton.disabled = true;
      return;
    }
    await listen("synthesis-finished", async ({ payload }) => {
      if (payload.result?.Ok) {
        synthesisArea.hidden = true;
        chooseButton.disabled = false;
        chooseButton.dataset.selected = "";
        startButton.hidden = true;
        await showSession(payload.result.Ok);
      } else {
        synthesisArea.hidden = true;
        chooseButton.disabled = false;
        startButton.hidden = false;
        reportError(payload.result?.Err || "Speech generation failed.");
      }
    });
    try {
      const savedSession = await invoke("current_session");
      if (savedSession) await showSession(savedSession);
    } catch (error) {
      reportError(error);
    }
  }

  void initialize();
})();

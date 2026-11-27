import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FrontendSession, Progress, StreamingSnapshot, SynthesisFinished, SynthesisProgress } from "../lib/tauri";

const SHA = "ab".repeat(32);
const BASE = "http://127.0.0.1:5555/v1/token";

// Three passages: starts at 0 s, 10 s and 30 s; 60 s in total.
const session: FrontendSession = {
  sourceName: "paper.pdf",
  sourceSha256: SHA,
  narrationRulesetVersion: "rules-7",
  voice: "en_US-ryan-medium",
  sampleRate: 22050,
  channels: 1,
  sampleWidthBytes: 2,
  audioBaseUrl: BASE,
  chunks: [
    { durationSeconds: 10, pauseAfterMs: 0, unitId: "u-a" },
    { durationSeconds: 20, pauseAfterMs: 400, unitId: "u-b" },
    { durationSeconds: 30, pauseAfterMs: 0, unitId: "u-c" },
  ],
};

const tauri = vi.hoisted(() => ({
  savedProgress: null as Progress | null,
  saveProgress: vi.fn().mockResolvedValue(undefined),
  // null: no session was open at launch.
  current: undefined as FrontendSession | null | undefined,
  snapshot: null as StreamingSnapshot | null,
  onProgress: null as ((payload: SynthesisProgress) => void) | null,
  onFinished: null as ((payload: SynthesisFinished) => void) | null,
}));

vi.mock("../lib/tauri", async () => {
  const actual = await vi.importActual<typeof import("../lib/tauri")>("../lib/tauri");
  return {
    ...actual,
    isTauriAvailable: () => true,
    currentSession: vi.fn(async () => (tauri.current === undefined ? session : tauri.current)),
    streamingSession: vi.fn(async () => tauri.snapshot),
    loadProgress: vi.fn(async () => tauri.savedProgress),
    saveProgress: tauri.saveProgress,
    listVoices: vi.fn(async () => []),
    listLibrary: vi.fn(async () => []),
    onSynthesisFinished: vi.fn(async (handler: (payload: SynthesisFinished) => void) => {
      tauri.onFinished = handler;
      return () => {};
    }),
    onSynthesisProgress: vi.fn(async (handler: (payload: SynthesisProgress) => void) => {
      tauri.onProgress = handler;
      return () => {};
    }),
  };
});

const { useSonara } = await import("./useSonara");

let audio: HTMLAudioElement;
let play: ReturnType<typeof vi.fn>;

function setReadyState(value: number) {
  Object.defineProperty(audio, "readyState", { configurable: true, get: () => value });
}

async function renderReadyPlayer() {
  const hook = renderHook(() => useSonara());
  // Attach the element before the async session restore reaches loadChunk.
  hook.result.current.audioRef.current = audio;
  await waitFor(() => expect(hook.result.current.phase).toBe("ready"));
  await waitFor(() => expect(hook.result.current.playerState.totalDuration).toBe(60));
  return hook;
}

beforeEach(() => {
  tauri.savedProgress = null;
  tauri.current = undefined;
  tauri.snapshot = null;
  tauri.onProgress = null;
  tauri.onFinished = null;
  tauri.saveProgress.mockClear();
  localStorage.clear();
  audio = document.createElement("audio");
  // jsdom does not implement media playback.
  play = vi.fn().mockResolvedValue(undefined);
  audio.play = play as unknown as HTMLMediaElement["play"];
  audio.pause = vi.fn();
  audio.load = vi.fn();
  Object.defineProperty(audio, "duration", { configurable: true, value: 10 });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useSonara player", () => {
  it("restores saved progress: passage, offset and speed", async () => {
    tauri.savedProgress = { version: 2, sourceSha256: SHA, segment: 1, offsetSeconds: 5, playbackRate: 1.2 } as Progress;
    const { result } = await renderReadyPlayer();
    expect(result.current.playerState.segment).toBe(1);
    expect(audio.src).toBe(`${BASE}/${SHA}/1`);
    expect(result.current.playerState.playbackRate).toBe(1.2);
    expect(result.current.playerState.globalPosition).toBe(15);
    expect(result.current.playerState.statusMessage).toBe("Reading progress restored.");
  });

  it("loads the restored passage when the audio element mounts after the restore", async () => {
    // The player mounts in the same render that shows the session, and the
    // progress restore can finish first. Found by the desktop E2E test.
    tauri.savedProgress = { version: 2, sourceSha256: SHA, segment: 2, offsetSeconds: 4, playbackRate: 1 } as Progress;
    const { result } = renderHook(() => useSonara());
    await waitFor(() => expect(result.current.playerState.totalDuration).toBe(60));
    expect(audio.src).toBe("");
    act(() => result.current.attachAudio(audio));
    expect(audio.src).toBe(`${BASE}/${SHA}/2`);
    expect(audio.load).toHaveBeenCalled();
    expect(result.current.playerState.statusMessage).toBe("Loading passage 3 of 3…");
  });

  it("restores by narration unit when passages were renumbered", async () => {
    // Saved at index 0, but that unit is now the third passage.
    tauri.savedProgress = { version: 2, sourceSha256: SHA, segment: 0, offsetSeconds: 3, playbackRate: 1, unitId: "u-c" } as Progress;
    const { result } = await renderReadyPlayer();
    expect(result.current.playerState.segment).toBe(2);
    expect(result.current.playerState.globalPosition).toBe(33);
  });

  it("falls back to the saved index when the unit is unknown", async () => {
    tauri.savedProgress = { version: 2, sourceSha256: SHA, segment: 1, offsetSeconds: 2, playbackRate: 1, unitId: "gone" } as Progress;
    const { result } = await renderReadyPlayer();
    expect(result.current.playerState.segment).toBe(1);
  });

  it("ignores saved progress that does not fit the document", async () => {
    tauri.savedProgress = { version: 2, sourceSha256: SHA, segment: 1, offsetSeconds: 999, playbackRate: 1.2 } as Progress;
    const { result } = await renderReadyPlayer();
    expect(result.current.playerState.segment).toBe(0);
    expect(result.current.playerState.playbackRate).toBe(1);
    expect(result.current.playerState.statusMessage).toBe("Ready to play.");
  });

  it("maps a document position to the right passage and saves it", async () => {
    const { result } = await renderReadyPlayer();
    act(() => result.current.seekTo(35));
    expect(result.current.playerState.segment).toBe(2);
    expect(audio.src).toBe(`${BASE}/${SHA}/2`);
    await waitFor(() =>
      expect(tauri.saveProgress).toHaveBeenLastCalledWith(
        expect.objectContaining({ version: 2, segment: 2, offsetSeconds: 5, unitId: "u-c" }),
      ),
    );
    // Positions past the end clamp to the last passage.
    act(() => result.current.seekTo(10_000));
    expect(result.current.playerState.segment).toBe(2);
  });

  it("clamps speed to 0.7–1.5× in 0.1 steps", async () => {
    const { result } = await renderReadyPlayer();
    act(() => result.current.setSpeed(3));
    expect(result.current.playerState.playbackRate).toBe(1.5);
    expect(audio.playbackRate).toBe(1.5);
    act(() => result.current.setSpeed(0.1));
    expect(result.current.playerState.playbackRate).toBe(0.7);
    act(() => result.current.setSpeed(1.04));
    expect(result.current.playerState.playbackRate).toBe(1);
  });

  it("plays, pauses and explains a blocked autoplay", async () => {
    const { result } = await renderReadyPlayer();
    await act(() => result.current.startPlayback());
    expect(play).toHaveBeenCalled();
    expect(result.current.playerState.isPlaying).toBe(true);

    act(() => result.current.pausePlayback());
    expect(result.current.playerState.isPlaying).toBe(false);

    play.mockRejectedValueOnce(Object.assign(new Error("blocked"), { name: "NotAllowedError" }));
    await act(() => result.current.startPlayback());
    expect(result.current.playerState.isPlaying).toBe(false);
    expect(result.current.playerState.statusMessage).toMatch(/blocked playback/);
  });

  it("waits out the pause between passages before loading the next one", async () => {
    const { result } = await renderReadyPlayer();
    act(() => result.current.seekToChunk(1));
    vi.useFakeTimers();
    act(() => result.current.handleEnded());
    expect(result.current.playerState.statusMessage).toBe("Pause between passages…");
    expect(result.current.playerState.segment).toBe(1);
    act(() => vi.advanceTimersByTime(400));
    expect(result.current.playerState.segment).toBe(2);
    expect(audio.src).toBe(`${BASE}/${SHA}/2`);
  });

  it("stops at the last passage", async () => {
    const { result } = await renderReadyPlayer();
    act(() => result.current.seekToChunk(2));
    act(() => result.current.handleEnded());
    expect(result.current.playerState.segment).toBe(2);
    expect(result.current.playerState.statusMessage).toBe("You have reached the end of this document.");
  });

  it("offers retry and skip when a passage does not load in time", async () => {
    const { result } = await renderReadyPlayer();
    setReadyState(0);
    vi.useFakeTimers();
    act(() => result.current.seekToChunk(0));
    act(() => vi.advanceTimersByTime(12_000));
    expect(result.current.playerState.hasError).toBe(true);
    expect(result.current.playerState.canRetry).toBe(true);
    expect(result.current.playerState.canSkip).toBe(true);
    expect(result.current.playerState.errorMessage).toMatch(/did not load within 12 seconds/);

    act(() => result.current.skipPassage());
    expect(result.current.playerState.segment).toBe(1);
    expect(result.current.playerState.hasError).toBe(false);
  });

  it("ignores media events from a stale source", async () => {
    const { result } = await renderReadyPlayer();
    // Browsers set currentSrc once a source loads; jsdom leaves it empty.
    let currentSrc = `${BASE}/${SHA}/99`;
    Object.defineProperty(audio, "currentSrc", { configurable: true, get: () => currentSrc });
    act(() => result.current.handleError());
    expect(result.current.playerState.hasError).toBe(false);

    // The same event from the expected passage is reported.
    currentSrc = `${BASE}/${SHA}/0`;
    act(() => result.current.handleError());
    expect(result.current.playerState.hasError).toBe(true);
  });

  it("toggles playback with Space but not with Ctrl+Space or from a focused button", async () => {
    const { result } = await renderReadyPlayer();
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: " ", ctrlKey: true }));
    });
    expect(play).not.toHaveBeenCalled();

    const button = document.createElement("button");
    document.body.appendChild(button);
    act(() => {
      button.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));
    });
    expect(play).not.toHaveBeenCalled();
    button.remove();

    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: " " }));
    });
    expect(play).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.playerState.isPlaying).toBe(true));
  });
});


describe("useSonara streaming playback", () => {
  const partial = (count: number): FrontendSession => ({ ...session, chunks: session.chunks.slice(0, count) });

  /** A launch with no open session, then a run whose first passage is ready. */
  async function renderStreaming(ready = 1) {
    tauri.current = null;
    const hook = renderHook(() => useSonara());
    hook.result.current.audioRef.current = audio;
    await waitFor(() => expect(tauri.onProgress).not.toBeNull());
    await act(async () => {
      tauri.onProgress!({ jobId: "job", completedChunks: ready, totalChunks: 3, firstChunk: 0, newChunks: [], session: partial(ready) });
    });
    await waitFor(() => expect(hook.result.current.phase).toBe("streaming"));
    return hook;
  }

  async function addPassages(firstChunk: number, count: number) {
    await act(async () => {
      tauri.onProgress!({
        jobId: "job",
        completedChunks: firstChunk + count,
        totalChunks: 3,
        firstChunk,
        newChunks: session.chunks.slice(firstChunk, firstChunk + count),
      });
    });
  }

  it("plays the first passage before the rest are synthesized", async () => {
    const { result } = await renderStreaming();
    expect(audio.src).toBe(`${BASE}/${SHA}/0`);
    expect(result.current.playerState.isComplete).toBe(false);
    expect(result.current.playerState.expectedChunks).toBe(3);
    expect(result.current.playerState.totalDuration).toBe(10);
    // Two more passages at the 10 s average of the ready one.
    expect(result.current.playerState.estimatedDuration).toBe(30);
    expect(result.current.statusText).toContain("1 of 3 passages ready");
  });

  it("waits at the end of the ready passages, then resumes when the next arrives", async () => {
    const { result } = await renderStreaming();
    await act(async () => {
      await result.current.startPlayback();
    });
    act(() => result.current.handleEnded());
    expect(result.current.playerState.isBuffering).toBe(true);
    expect(result.current.playerState.statusMessage).toBe("Preparing passage 2 of 3…");
    expect(result.current.playerState.statusMessage).not.toContain("end of this document");

    await addPassages(1, 1);
    expect(audio.src).toBe(`${BASE}/${SHA}/1`);
    expect(result.current.playerState.isBuffering).toBe(false);
    expect(result.current.session?.chunks).toHaveLength(2);
    // It was playing when it ran out, so it carries on by itself.
    setReadyState(HTMLMediaElement.HAVE_METADATA);
    await act(async () => {
      await result.current.handleLoadedMetadata();
    });
    expect(play).toHaveBeenCalledTimes(2);
  });

  it("does not save a position while waiting for a passage", async () => {
    const { result } = await renderStreaming();
    act(() => result.current.seekToChunk(2));
    expect(result.current.playerState.isBuffering).toBe(true);
    act(() => result.current.pausePlayback());
    await Promise.resolve();
    expect(tauri.saveProgress).not.toHaveBeenCalledWith(expect.objectContaining({ segment: 2 }));
  });

  it("holds a saved position until its passage is synthesized", async () => {
    tauri.savedProgress = { version: 2, sourceSha256: SHA, segment: 2, offsetSeconds: 4, playbackRate: 1.3, unitId: "u-c" } as Progress;
    const { result } = await renderStreaming();
    expect(result.current.playerState.isBuffering).toBe(true);
    expect(result.current.playerState.statusMessage).toContain("continue where you left off");
    expect(result.current.playerState.playbackRate).toBe(1.3);

    await addPassages(1, 1);
    expect(result.current.playerState.isBuffering).toBe(true);
    await addPassages(2, 1);
    expect(audio.src).toBe(`${BASE}/${SHA}/2`);
    expect(result.current.playerState.globalPosition).toBe(34);
    expect(result.current.playerState.statusMessage).toBe("Reading progress restored.");
  });

  it("catches up from the backend after a missed progress event", async () => {
    const { result } = await renderStreaming();
    tauri.snapshot = { jobId: "job", totalChunks: 3, session: partial(3) };
    // Passage 1 was never announced; this event starts at passage 2.
    await addPassages(2, 1);
    expect(result.current.session?.chunks).toHaveLength(3);
    expect(result.current.playerState.totalDuration).toBe(60);
  });

  it("keeps the listening position when the run finishes", async () => {
    const { result } = await renderStreaming(2);
    act(() => result.current.seekToChunk(1));
    expect(audio.src).toBe(`${BASE}/${SHA}/1`);
    await act(async () => {
      tauri.onFinished!({ jobId: "job", result: { Ok: session } });
    });
    expect(result.current.phase).toBe("ready");
    expect(result.current.playerState.isComplete).toBe(true);
    expect(result.current.playerState.segment).toBe(1);
    expect(audio.src).toBe(`${BASE}/${SHA}/1`);
    expect(result.current.statusText).toBe("Ready to listen · 3 passages · en_US-ryan-medium");
  });

  it("reaches the end of the document only after the last planned passage", async () => {
    const { result } = await renderStreaming(2);
    act(() => result.current.seekToChunk(1));
    vi.useFakeTimers();
    act(() => result.current.handleEnded());
    // Passage 2 is followed by a planned 400 ms pause.
    act(() => vi.advanceTimersByTime(400));
    expect(result.current.playerState.isBuffering).toBe(true);
    expect(result.current.playerState.statusMessage).toBe("Preparing passage 3 of 3…");

    await addPassages(2, 1);
    expect(audio.src).toBe(`${BASE}/${SHA}/2`);
    expect(result.current.playerState.isComplete).toBe(true);
    act(() => result.current.handleEnded());
    expect(result.current.playerState.isBuffering).toBe(false);
    expect(result.current.playerState.statusMessage).toBe("You have reached the end of this document.");
  });

  it("returns to the previous session when a streaming run is cancelled", async () => {
    const other: FrontendSession = { ...session, sourceName: "earlier.pdf", sourceSha256: "cd".repeat(32) };
    tauri.current = other;
    const hook = renderHook(() => useSonara());
    hook.result.current.audioRef.current = audio;
    await waitFor(() => expect(hook.result.current.phase).toBe("ready"));
    await act(async () => {
      tauri.onProgress!({ jobId: "job", completedChunks: 1, totalChunks: 3, firstChunk: 0, newChunks: [], session: partial(1) });
    });
    expect(hook.result.current.session?.sourceSha256).toBe(SHA);

    await act(async () => {
      tauri.onFinished!({ jobId: "job", result: { Err: "Speech generation was cancelled." } });
    });
    expect(hook.result.current.session?.sourceName).toBe("earlier.pdf");
    expect(hook.result.current.phase).toBe("selected");
    expect(audio.src).toBe(`${BASE}/${"cd".repeat(32)}/0`);
  });
});

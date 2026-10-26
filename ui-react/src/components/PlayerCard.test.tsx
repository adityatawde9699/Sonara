import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PlayerCard } from "./PlayerCard";
import type { FrontendSession } from "../lib/tauri";
import type { PlayerState } from "../hooks/useSonara";

const mockSession: FrontendSession = {
  sourceName: "sample_article.pdf",
  sourceSha256: "sha256-abcdef",
  narrationRulesetVersion: "1",
  voice: "en_US-john-medium",
  sampleRate: 22050,
  channels: 1,
  sampleWidthBytes: 2,
  audioBaseUrl: "http://127.0.0.1:5432/audio",
  chunks: [
    { durationSeconds: 10, pauseAfterMs: 300 },
    { durationSeconds: 15, pauseAfterMs: 400 },
    { durationSeconds: 12, pauseAfterMs: 0 },
  ],
};

const defaultPlayerState: PlayerState = {
  isPlaying: false,
  segment: 0,
  globalPosition: 5,
  totalDuration: 37,
  playbackRate: 1.0,
  hasError: false,
  errorMessage: "",
  statusMessage: "Ready to play.",
  canRetry: false,
  canSkip: false,
};

describe("PlayerCard component", () => {
  it("renders document title, voice and transport buttons", () => {
    const audioRef = { current: document.createElement("audio") };
    render(
      <PlayerCard
        session={mockSession}
        state={defaultPlayerState}
        audioRef={audioRef}
        chunkStarts={[0, 10, 25]}
        onPlay={vi.fn()}
        onPause={vi.fn()}
        onSeek={vi.fn()}
        onSeekChunk={vi.fn()}
        onSpeedChange={vi.fn()}
        onRetry={vi.fn()}
        onSkip={vi.fn()}
        onLoadedMetadata={vi.fn()}
        onTimeUpdate={vi.fn()}
        onError={vi.fn()}
        onPlaying={vi.fn()}
        onEnded={vi.fn()}
        onCanPlay={vi.fn()}
        onWaiting={vi.fn()}
      />
    );

    expect(screen.getByText("sample_article.pdf")).toBeInTheDocument();
    expect(screen.getByText("en_US-john-medium")).toBeInTheDocument();

    const playBtn = screen.getByRole("button", { name: /Play audio narration/i });
    const pauseBtn = screen.getByRole("button", { name: /Pause audio narration/i });

    expect(playBtn).toBeEnabled();
    expect(pauseBtn).toBeDisabled();
  });

  it("calls onPlay when Play button is clicked", () => {
    const onPlay = vi.fn();
    const audioRef = { current: document.createElement("audio") };
    render(
      <PlayerCard
        session={mockSession}
        state={defaultPlayerState}
        audioRef={audioRef}
        chunkStarts={[0, 10, 25]}
        onPlay={onPlay}
        onPause={vi.fn()}
        onSeek={vi.fn()}
        onSeekChunk={vi.fn()}
        onSpeedChange={vi.fn()}
        onRetry={vi.fn()}
        onSkip={vi.fn()}
        onLoadedMetadata={vi.fn()}
        onTimeUpdate={vi.fn()}
        onError={vi.fn()}
        onPlaying={vi.fn()}
        onEnded={vi.fn()}
        onCanPlay={vi.fn()}
        onWaiting={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Play audio narration/i }));
    expect(onPlay).toHaveBeenCalledTimes(1);
  });

  it("renders interactive passage dots and triggers onSeekChunk", () => {
    const onSeekChunk = vi.fn();
    const audioRef = { current: document.createElement("audio") };
    render(
      <PlayerCard
        session={mockSession}
        state={defaultPlayerState}
        audioRef={audioRef}
        chunkStarts={[0, 10, 25]}
        onPlay={vi.fn()}
        onPause={vi.fn()}
        onSeek={vi.fn()}
        onSeekChunk={onSeekChunk}
        onSpeedChange={vi.fn()}
        onRetry={vi.fn()}
        onSkip={vi.fn()}
        onLoadedMetadata={vi.fn()}
        onTimeUpdate={vi.fn()}
        onError={vi.fn()}
        onPlaying={vi.fn()}
        onEnded={vi.fn()}
        onCanPlay={vi.fn()}
        onWaiting={vi.fn()}
      />
    );

    const dot2 = screen.getByLabelText("Jump to passage 2 of 3");
    expect(dot2).toBeInTheDocument();
    expect(screen.getByText("Passages")).toBeInTheDocument();
    expect(screen.getByText("Passage 1 of 3")).toBeInTheDocument();

    fireEvent.click(dot2);
    expect(onSeekChunk).toHaveBeenCalledWith(1);
  });

  it("renders retry and skip buttons when errors are reported", () => {
    const onRetry = vi.fn();
    const onSkip = vi.fn();
    const errorState: PlayerState = {
      ...defaultPlayerState,
      hasError: true,
      canRetry: true,
      canSkip: true,
      errorMessage: "Passage 1 failed to decode.",
    };

    const audioRef = { current: document.createElement("audio") };
    render(
      <PlayerCard
        session={mockSession}
        state={errorState}
        audioRef={audioRef}
        chunkStarts={[0, 10, 25]}
        onPlay={vi.fn()}
        onPause={vi.fn()}
        onSeek={vi.fn()}
        onSeekChunk={vi.fn()}
        onSpeedChange={vi.fn()}
        onRetry={onRetry}
        onSkip={onSkip}
        onLoadedMetadata={vi.fn()}
        onTimeUpdate={vi.fn()}
        onError={vi.fn()}
        onPlaying={vi.fn()}
        onEnded={vi.fn()}
        onCanPlay={vi.fn()}
        onWaiting={vi.fn()}
      />
    );

    expect(screen.getByText("Passage 1 failed to decode.")).toBeInTheDocument();
    const retryBtn = screen.getByRole("button", { name: /Retry current passage/i });
    const skipBtn = screen.getByRole("button", { name: /Skip to next passage/i });

    expect(retryBtn).toBeInTheDocument();
    expect(skipBtn).toBeInTheDocument();

    fireEvent.click(retryBtn);
    expect(onRetry).toHaveBeenCalledTimes(1);

    fireEvent.click(skipBtn);
    expect(onSkip).toHaveBeenCalledTimes(1);
  });
});

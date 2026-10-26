import { type FC, useCallback, useRef } from "react";
import type { FrontendSession } from "../lib/tauri";
import type { PlayerState } from "../hooks/useSonara";

interface Props {
  session: FrontendSession;
  state: PlayerState;
  voiceLabel?: string;
  audioRef: React.RefObject<HTMLAudioElement | null>;
  chunkStarts: number[];
  onPlay: () => void;
  onPause: () => void;
  onSeek: (position: number) => void;
  onSeekChunk: (chunkIndex: number) => void;
  onSpeedChange: (rate: number) => void;
  onRetry: () => void;
  onSkip: () => void;
  onLoadedMetadata: () => void;
  onTimeUpdate: () => void;
  onError: () => void;
  onPlaying: () => void;
  onEnded: () => void;
  onCanPlay: () => void;
  onWaiting: () => void;
}

function formatClock(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds || 0));
  const mins = Math.floor(value / 60);
  const secs = value % 60;
  return `${mins}:${secs < 10 ? `0${secs}` : secs}`;
}

export const PlayerCard: FC<Props> = ({
  session,
  state,
  voiceLabel,
  audioRef,
  chunkStarts,
  onPlay,
  onPause,
  onSeek,
  onSeekChunk,
  onSpeedChange,
  onRetry,
  onSkip,
  onLoadedMetadata,
  onTimeUpdate,
  onError,
  onPlaying,
  onEnded,
  onCanPlay,
  onWaiting,
}) => {
  const seekRef = useRef<HTMLInputElement>(null);

  const handleSeekChange = useCallback(() => {
    const seek = seekRef.current;
    if (!seek) return;
    const position = (Number(seek.value) / 1000) * state.totalDuration;
    onSeek(position);
  }, [onSeek, state.totalDuration]);

  const handleSpeedInput = useCallback(
    (e: React.FormEvent<HTMLInputElement>) => {
      onSpeedChange(Number((e.target as HTMLInputElement).value));
    },
    [onSpeedChange]
  );

  const seekValue = state.totalDuration
    ? Math.round((state.globalPosition / state.totalDuration) * 1000)
    : 0;

  const progressPercent = state.totalDuration
    ? Math.min(100, Math.max(0, (state.globalPosition / state.totalDuration) * 100))
    : 0;

  return (
    <section className="player-card" aria-labelledby="player-title" role="region">
      <div className="player-heading">
        <div>
          <h2 id="player-title">{session.sourceName}</h2>
        </div>
        <span className="voice-label" title={`Voice: ${session.voice}`}>
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ marginRight: 5, verticalAlign: -1 }}
            aria-hidden="true"
          >
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>
          {voiceLabel || session.voice}
        </span>
      </div>

      {/* Hidden audio element supervised by React */}
      <audio
        ref={audioRef}
        preload="metadata"
        onLoadedMetadata={onLoadedMetadata}
        onTimeUpdate={onTimeUpdate}
        onError={onError}
        onPlaying={onPlaying}
        onEnded={onEnded}
        onCanPlay={onCanPlay}
        onWaiting={onWaiting}
      />

      {/* Transport controls */}
      <div className="transport" role="toolbar" aria-label="Audio controls">
        <button
          id="play"
          className="button button-primary transport-btn"
          type="button"
          disabled={state.isPlaying || !session.chunks.length}
          onClick={onPlay}
          aria-label="Play audio narration"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
          <span>Play</span>
        </button>
        <button
          id="pause"
          className="button button-secondary transport-btn"
          type="button"
          disabled={!state.isPlaying}
          onClick={onPause}
          aria-label="Pause audio narration"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <rect x="6" y="4" width="4" height="16" />
            <rect x="14" y="4" width="4" height="16" />
          </svg>
          <span>Pause</span>
        </button>
        {state.canRetry && (
          <button id="retry" className="text-button" type="button" onClick={onRetry} aria-label="Retry current passage">
            ↻ Retry passage
          </button>
        )}
        {state.canSkip && (
          <button id="skip" className="text-button" type="button" onClick={onSkip} aria-label="Skip to next passage">
            ⏭ Skip passage
          </button>
        )}
      </div>

      {/* Seek slider */}
      <div className="seek-section">
        <label className="range-label" htmlFor="seek">
          <span>Position</span>
          <span id="position-label" className="mono">
            {formatClock(state.globalPosition)} / {formatClock(state.totalDuration)}
          </span>
        </label>
        <div className="range-track-wrapper">
          <div className="range-track-fill" style={{ width: `${progressPercent}%` }} />
          <input
            ref={seekRef}
            id="seek"
            className="range"
            type="range"
            min="0"
            max="1000"
            value={seekValue}
            onChange={handleSeekChange}
            aria-label="Seek through document"
            aria-valuemin={0}
            aria-valuemax={1000}
            aria-valuenow={seekValue}
            aria-valuetext={`${formatClock(state.globalPosition)} of ${formatClock(state.totalDuration)}`}
          />
        </div>
      </div>

      {/* Speed control */}
      <div className="speed-control">
        <label className="range-label" htmlFor="speed">
          <span>Listening speed</span>
          <span id="speed-label" className="mono">{state.playbackRate.toFixed(1)}×</span>
        </label>
        <div className="range-track-wrapper">
          <div
            className="range-track-fill"
            style={{ width: `${Math.min(100, Math.max(0, ((state.playbackRate - 0.7) / 0.8) * 100))}%` }}
          />
          <input
            id="speed"
            className="range"
            type="range"
            min="0.7"
            max="1.5"
            step="0.1"
            value={state.playbackRate}
            onInput={handleSpeedInput}
            aria-label="Adjust playback speed"
            aria-valuemin={0.7}
            aria-valuemax={1.5}
            aria-valuenow={state.playbackRate}
            aria-valuetext={`${state.playbackRate.toFixed(1)}x speed`}
          />
        </div>
      </div>

      {/* Status */}
      <p
        id="player-status"
        className={`status ${state.hasError ? "error" : ""}`}
        role="status"
        aria-live="polite"
      >
        {state.hasError ? state.errorMessage : state.statusMessage}
      </p>

      {/* Passage navigation reflects the actual generated audio chunks. */}
      <div className="passage-navigation">
        <div className="passage-navigation-label">
          <span>Passages</span>
          <span>Passage {state.segment + 1} of {session.chunks.length}</span>
        </div>
        <div className="passage-dots" role="group" aria-label={`Passages: currently on passage ${state.segment + 1} of ${session.chunks.length}`}>
          {session.chunks.length <= 16 && session.chunks.map((chunk, i) => {
            const isCurrent = i === state.segment;
            const isDone = i < state.segment;
            const startTime = chunkStarts[i] ?? 0;
            return (
              <button
                key={i}
                type="button"
                className={`dot${isCurrent ? " active" : ""}${isDone ? " done" : ""}`}
                onClick={() => onSeekChunk(i)}
                title={`Passage ${i + 1} (${formatClock(startTime)}, ${chunk.durationSeconds.toFixed(1)}s)`}
                aria-label={`Jump to passage ${i + 1} of ${session.chunks.length}`}
                aria-current={isCurrent ? "step" : undefined}
              />
            );
          })}
          {session.chunks.length > 16 && (
            <span className="passage-count">Use Position above to move through passages.</span>
          )}
        </div>
      </div>
    </section>
  );
};

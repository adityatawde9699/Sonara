import { type FC, useCallback, useRef } from "react";
import type { FrontendSession } from "../lib/tauri";
import type { PlayerState } from "../hooks/useSonara";
import { FileText, Mic, Pause, Play, RotateCcw, RotateCw, SkipBack, SkipForward } from "lucide-react";

interface Props {
  session: FrontendSession;
  state: PlayerState;
  voiceLabel?: string;
  audioRef: React.Ref<HTMLAudioElement>;
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

  const seekValue = state.totalDuration
    ? Math.round((state.globalPosition / state.totalDuration) * 1000)
    : 0;

  const progressPercent = state.totalDuration
    ? Math.min(100, Math.max(0, (state.globalPosition / state.totalDuration) * 100))
    : 0;

  // While the rest is synthesized, only the ready passages can be reached.
  const plannedChunks = Math.max(state.expectedChunks, session.chunks.length);
  const streaming = !state.isComplete;

  return (
    <section className="player-card" aria-labelledby="player-title" role="region">
      <div className="player-heading">
        <span className="player-art" aria-hidden="true">
          <FileText size={18} aria-hidden="true" />
        </span>
        <div className="player-copy">
          <p className="player-kicker">Now listening</p>
          <h2 id="player-title" title={session.sourceName}>{session.sourceName}</h2>
          <span className="voice-label" title={`Voice: ${session.voice}`}>
            <Mic size={16} aria-hidden="true" />
            {voiceLabel || session.voice}
          </span>
        </div>
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
      <div className="player-center">
      <div className="transport" role="toolbar" aria-label="Audio controls">
        <button
          className="player-icon-button"
          type="button"
          aria-label="Previous passage"
          title="Previous passage"
          disabled={state.segment === 0}
          onClick={() => onSeekChunk(Math.max(0, state.segment - 1))}
        >
          <SkipBack size={16} fill="currentColor" aria-hidden="true" />
        </button>
        <button
          className="player-icon-button skip-button"
          type="button"
          aria-label="Back 10 seconds"
          title="Back 10 seconds"
          disabled={state.globalPosition <= 0}
          onClick={() => onSeek(Math.max(0, state.globalPosition - 10))}
        >
          <RotateCcw size={16} aria-hidden="true" />
        </button>
        <button
          id={state.isPlaying ? "pause" : "play"}
          className={`button ${state.isPlaying ? "button-secondary" : "button-primary"} transport-btn`}
          type="button"
          disabled={!session.chunks.length}
          onClick={state.isPlaying ? onPause : onPlay}
          aria-label={`${state.isPlaying ? "Pause" : "Play"} audio narration`}
        >
          {state.isPlaying
            ? <Pause size={16} fill="currentColor" aria-hidden="true" />
            : <Play size={16} fill="currentColor" aria-hidden="true" />}
        </button>
        <button
          className="player-icon-button skip-button"
          type="button"
          aria-label="Forward 10 seconds"
          title="Forward 10 seconds"
          disabled={state.globalPosition >= state.totalDuration}
          onClick={() => onSeek(Math.min(state.totalDuration, state.globalPosition + 10))}
        >
          <RotateCw size={16} aria-hidden="true" />
        </button>
        <button
          className="player-icon-button"
          type="button"
          aria-label="Next passage"
          title="Next passage"
          disabled={state.segment >= plannedChunks - 1}
          onClick={() => onSeekChunk(Math.min(plannedChunks - 1, state.segment + 1))}
        >
          <SkipForward size={16} fill="currentColor" aria-hidden="true" />
        </button>
        {state.canRetry && (
          <button id="retry" className="text-button" type="button" onClick={onRetry} aria-label="Retry current passage">
            <RotateCcw size={16} aria-hidden="true" />Retry passage
          </button>
        )}
        {state.canSkip && (
          <button id="skip" className="text-button" type="button" onClick={onSkip} aria-label="Skip to next passage">
            <SkipForward size={16} aria-hidden="true" />Skip passage
          </button>
        )}
      </div>

      {/* Seek slider */}
      <div className="seek-section">
        <label className="range-label" htmlFor="seek">
          <span>Position</span>
          <span id="position-label" className="mono">
            {formatClock(state.globalPosition)} / {formatClock(state.totalDuration)}
            {streaming && (
              <span className="position-estimate" title="Estimated from the passages prepared so far">
                {" "}ready · about {formatClock(state.estimatedDuration)} in all
              </span>
            )}
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
            aria-valuetext={`${formatClock(state.globalPosition)} of ${formatClock(state.totalDuration)}${streaming ? " prepared so far" : ""}`}
          />
        </div>
      </div>
      <p
        id="player-status"
        className={`status ${state.hasError ? "error" : ""}`}
        role="status"
        aria-live="polite"
      >
        {state.hasError ? state.errorMessage : state.statusMessage}
      </p>
      </div>

      {/* Speed control */}
      <div className="player-extra">
      <div className="speed-control">
        <label className="range-label" htmlFor="speed">
          <span>Listening speed</span>
          <span id="speed-label" className="mono">{state.playbackRate.toFixed(1)}×</span>
        </label>
        <select id="speed" className="speed-select" value={state.playbackRate} onChange={(event) => onSpeedChange(Number(event.target.value))} aria-label="Adjust playback speed">
          {[0.7, 0.8, 0.9, 1, 1.1, 1.2, 1.3, 1.4, 1.5].map((speed) => <option key={speed} value={speed}>{speed.toFixed(1)}×</option>)}
        </select>
      </div>

      {/* Passage navigation reflects the actual generated audio chunks. */}
      <div className="passage-navigation">
        <div className="passage-navigation-label">
          <span>Passages</span>
          <span>
            Passage {state.segment + 1} of {plannedChunks}
            {streaming && ` · ${session.chunks.length} ready`}
          </span>
        </div>
        <div className="passage-dots" role="group" aria-label={`Passages: currently on passage ${state.segment + 1} of ${plannedChunks}`}>
          {plannedChunks <= 64 && session.chunks.map((chunk, i) => {
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
                aria-label={`Jump to passage ${i + 1} of ${plannedChunks}`}
                aria-current={isCurrent ? "step" : undefined}
              />
            );
          })}
          {plannedChunks <= 64 && Array.from({ length: plannedChunks - session.chunks.length }, (_, k) => {
            const i = session.chunks.length + k;
            return (
              <span
                key={i}
                className={`dot pending${i === state.segment ? " active" : ""}`}
                title={`Passage ${i + 1} is being prepared`}
                aria-hidden="true"
              />
            );
          })}
          {plannedChunks > 64 && (
            <span className="passage-count">Use Position above to move through passages.</span>
          )}
        </div>
      </div>
      </div>
    </section>
  );
};

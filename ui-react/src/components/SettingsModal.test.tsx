import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SettingsModal } from "./SettingsModal";
import type { FrontendSession } from "../lib/tauri";

const mockSession: FrontendSession = {
  sourceName: "sample.pdf",
  sourceSha256: "abcd1234ef5678",
  narrationRulesetVersion: "1",
  voice: "en_US-john-medium",
  sampleRate: 22050,
  channels: 1,
  sampleWidthBytes: 2,
  audioBaseUrl: "http://127.0.0.1:4567/audio",
  chunks: [{ durationSeconds: 5, pauseAfterMs: 400 }],
};

describe("SettingsModal component", () => {
  it("does not render when isOpen is false", () => {
    const { container } = render(
      <SettingsModal
        isOpen={false}
        onClose={vi.fn()}
        session={mockSession}
        playbackRate={1.0}
        onSpeedChange={vi.fn()}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders speed presets and engine specifications", () => {
    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        session={mockSession}
        playbackRate={1.0}
        onSpeedChange={vi.fn()}
      />
    );

    expect(screen.getByText("Audio & Engine Settings")).toBeInTheDocument();
    expect(screen.getByText("1.0×")).toBeInTheDocument();
    expect(screen.getByText("1.2×")).toBeInTheDocument();
    expect(screen.getByText("en_US-john-medium")).toBeInTheDocument();
    expect(screen.getByText("22050 Hz · Mono · 16-bit PCM")).toBeInTheDocument();
    expect(screen.getByText(/100% Offline/)).toBeInTheDocument();
  });

  it("calls onSpeedChange when clicking a preset", () => {
    const onSpeedChange = vi.fn();
    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        session={mockSession}
        playbackRate={1.0}
        onSpeedChange={onSpeedChange}
      />
    );

    fireEvent.click(screen.getByText("1.2×"));
    expect(onSpeedChange).toHaveBeenCalledWith(1.2);
  });

  it("renders voice options and triggers onVoiceChange when selecting a different voice", () => {
    const onVoiceChange = vi.fn();
    const mockVoices = [
      { id: "en_US-ryan-medium", name: "Ryan (American Male · Natural)", quality: "medium", language: "en_US", isDefault: true },
      { id: "en_US-lessac-medium", name: "Lessac (American Female · Expressive)", quality: "medium", language: "en_US", isDefault: false },
    ];

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        session={mockSession}
        playbackRate={1.0}
        onSpeedChange={vi.fn()}
        voices={mockVoices}
        selectedVoice="en_US-ryan-medium"
        onVoiceChange={onVoiceChange}
      />
    );

    expect(screen.getByText("2 voices installed")).toBeInTheDocument();
    const select = screen.getByRole("combobox", { name: /narration voice/i });
    expect(select).toHaveValue("en_US-ryan-medium");

    fireEvent.change(select, { target: { value: "en_US-lessac-medium" } });
    expect(onVoiceChange).toHaveBeenCalledWith("en_US-lessac-medium");
  });
});

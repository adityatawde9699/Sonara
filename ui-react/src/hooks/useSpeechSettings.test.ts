import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { VoiceInfo } from "../lib/tauri";

const voices = vi.hoisted(() => ({ list: [] as VoiceInfo[] }));

vi.mock("../lib/tauri", async () => {
  const actual = await vi.importActual<typeof import("../lib/tauri")>("../lib/tauri");
  return { ...actual, listVoices: vi.fn(async () => voices.list) };
});

const { useSpeechSettings } = await import("./useSpeechSettings");

function voice(id: string, isDefault = false): VoiceInfo {
  return { id, name: id, quality: "medium", language: "en_US", isDefault };
}

describe("useSpeechSettings", () => {
  beforeEach(() => {
    localStorage.clear();
    voices.list = [];
  });

  it("restores stored settings and ignores a voice from the other engine", () => {
    localStorage.setItem("sonara_speech_engine", "kokoro");
    localStorage.setItem("sonara_selected_voice", "en_US-lessac-medium");
    localStorage.setItem("sonara_piper_variation", "more");
    localStorage.setItem("sonara_expand_dates", "true");
    const { result } = renderHook(() => useSpeechSettings(false));
    expect(result.current.speechEngine).toBe("kokoro");
    expect(result.current.selectedVoice).toBe("af_sarah");
    expect(result.current.piperVariation).toBe("more");
    expect(result.current.expandDates).toBe(true);
    expect(result.current.expandCitations).toBe(false);
  });

  it("switching engine selects that engine's default voice and persists both", () => {
    const { result } = renderHook(() => useSpeechSettings(false));
    act(() => result.current.setSpeechEngine("kokoro"));
    expect(result.current.selectedVoice).toBe("af_sarah");
    expect(localStorage.getItem("sonara_speech_engine")).toBe("kokoro");
    expect(localStorage.getItem("sonara_selected_voice")).toBe("af_sarah");
    act(() => result.current.setSpeechEngine("piper"));
    expect(result.current.selectedVoice).toBe("en_US-ryan-medium");
  });

  it("falls back to the installed default when the stored voice is missing", async () => {
    localStorage.setItem("sonara_selected_voice", "en_US-removed-medium");
    voices.list = [voice("en_US-lessac-medium"), voice("en_US-bryce-medium", true)];
    const { result } = renderHook(() => useSpeechSettings(true));
    await waitFor(() => expect(result.current.selectedVoice).toBe("en_US-bryce-medium"));
    expect(result.current.selectedVoiceName).toBe("en_US-bryce-medium");
    // The stored choice is kept, so reinstalling that voice restores it.
    expect(localStorage.getItem("sonara_selected_voice")).toBe("en_US-removed-medium");
  });
});

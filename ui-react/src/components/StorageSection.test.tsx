import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { StorageSection } from "./StorageSection";
import { formatBytes } from "../lib/format";
import * as tauri from "../lib/tauri";

vi.mock("../lib/tauri", async () => {
  const actual = await vi.importActual<typeof import("../lib/tauri")>("../lib/tauri");
  return { ...actual, storageUsage: vi.fn(), clearCache: vi.fn() };
});

const usage = (audio: number, embeddings: number): tauri.StorageUsage => ({
  audioCache: { bytes: audio, files: audio ? 3 : 0 },
  embeddingCache: { bytes: embeddings, files: embeddings ? 1 : 0 },
  sessions: { bytes: 5 * 1024 * 1024, files: 12 },
});

describe("StorageSection", () => {
  beforeEach(() => {
    vi.mocked(tauri.storageUsage).mockReset().mockResolvedValue(usage(300 * 1024 * 1024, 2048));
    vi.mocked(tauri.clearCache).mockReset().mockResolvedValue(usage(0, 2048));
  });

  it("shows sizes and clears the audio cache", async () => {
    render(<StorageSection />);
    expect(await screen.findByText("300 MB · 3 files")).toBeInTheDocument();
    expect(screen.getByText("2.0 KB · 1 file")).toBeInTheDocument();
    expect(screen.getByText("5.0 MB · 12 files")).toBeInTheDocument();
    // The open session cannot be cleared from here.
    expect(screen.getAllByRole("button", { name: /^Clear/ })).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Clear audio cache" }));
    await waitFor(() => expect(tauri.clearCache).toHaveBeenCalledWith("audio"));
    expect(await screen.findByText("Empty")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear audio cache" })).toBeDisabled();
  });

  it("shows why a clear was refused", async () => {
    vi.mocked(tauri.clearCache).mockRejectedValueOnce(new Error("Wait for speech preparation to finish."));
    render(<StorageSection />);
    fireEvent.click(await screen.findByRole("button", { name: "Clear audio cache" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wait for speech preparation");
  });

  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(20 * 1024 * 1024)).toBe("20 MB");
  });
});

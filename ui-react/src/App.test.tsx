import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { LibraryDocument } from "./lib/tauri";

/** A minimal desktop bridge whose library holds `documents`. */
function withDesktopLibrary(
  documents: Array<Omit<LibraryDocument, "engine" | "available">>,
  responses: Record<string, unknown> = {},
) {
  const library = documents.map((doc) => ({ engine: "Piper", available: true, ...doc }));
  const invoke = vi.fn(async (command: string): Promise<unknown> => {
    if (command in responses) return responses[command];
    if (command === "list_library") return library;
    if (command === "list_voices") return [];
    return null;
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).__TAURI__ = { core: { invoke }, event: { listen: vi.fn(async () => () => {}) } };
  return invoke;
}

afterEach(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (window as any).__TAURI__;
});

describe("Sonara workspace", () => {
  it("shows the honest first-run state and keeps desktop import disabled in browser preview", async () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "What would you like to listen to?" })).toBeInTheDocument();
    expect(screen.getByText("Nothing prepared yet.")).toBeInTheDocument();
    expect(screen.getByText("Choose a PDF, text, Markdown, Word, or EPUB file. Extraction and speech generation stay local.")).toBeInTheDocument();
    expect(screen.getByText("PDF · TXT/TEXT · MD · DOCX · EPUB")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Choose document/i })).toBeDisabled();
    expect(await screen.findByRole("note", { name: "Runtime notice" })).toBeInTheDocument();
  });

  it("opens and dismisses listening history from the primary navigation", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Listening history" }));
    expect(await screen.findByRole("dialog", { name: "Document History" })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Document History" })).not.toBeInTheDocument());
  });

  it("labels recent files from their names instead of assuming every session is a PDF", async () => {
    withDesktopLibrary([
      {
        sourceName: "Imported-notes.docx",
        sourceSha256: "docx-session",
        voice: "en_US-ryan-medium",
        chunksCount: 12,
        totalDurationSeconds: 540,
        lastListenedAt: Date.now(),
      },
    ]);

    render(<App />);

    expect(await screen.findByText("DOCX")).toBeInTheDocument();
    expect(screen.getByText("Imported-notes.docx")).toBeInTheDocument();
  });

  it("reopens a library document by hash and returns home ready to prepare it", async () => {
    const invoke = withDesktopLibrary(
      [{ sourceName: "Field Notes.pdf", sourceSha256: "field-notes", voice: "voice", chunksCount: 8, totalDurationSeconds: 600, lastListenedAt: 1000 }],
      { open_library_document: { displayName: "Field Notes.pdf" } },
    );
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /My Library/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Listen again: Field Notes.pdf" }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("open_library_document", { sourceSha256: "field-notes" }));
    expect(await screen.findByText("Selected from your library · ready to prepare speech")).toBeInTheDocument();
  });

  it("opens settings and keyboard shortcuts from their visible controls", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(await screen.findByRole("dialog", { name: "Audio & Engine Settings" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close settings dialog" }));
    fireEvent.click(screen.getByRole("button", { name: "Open keyboard shortcuts guide" }));
    expect(await screen.findByRole("dialog", { name: "Keyboard Shortcuts" })).toBeInTheDocument();
  });

  it("searches recent documents and persists favorite filtering in the library", async () => {
    withDesktopLibrary([
      { sourceName: "Field Notes.pdf", sourceSha256: "field-notes", voice: "voice", chunksCount: 8, totalDurationSeconds: 600, lastListenedAt: 1000 },
      { sourceName: "Annual Review.docx", sourceSha256: "annual-review", voice: "voice", chunksCount: 12, totalDurationSeconds: 900, lastListenedAt: 2000 },
    ]);
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /My Library/ }));
    expect(await screen.findByText("Field Notes.pdf")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search your library" }), { target: { value: "annual" } });
    expect(screen.getByText("Annual Review.docx")).toBeInTheDocument();
    expect(screen.queryByText("Field Notes.pdf")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search your library" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to favorites: Field Notes.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: "Favorites" }));
    expect(screen.getByText("Field Notes.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Annual Review.docx")).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("sonara_favorites") || "[]")).toContain("field-notes");
    localStorage.removeItem("sonara_favorites");
  });

  it("switches and persists the application appearance", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Switch to light appearance" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem("sonara_theme")).toBe("light");
    fireEvent.click(screen.getByRole("button", { name: "Switch to dark appearance" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    localStorage.removeItem("sonara_theme");
  });

  it("opens the assistant with A but leaves Ctrl+A and Cmd+A to the browser", async () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "a", ctrlKey: true });
    fireEvent.keyDown(window, { key: "a", metaKey: true });
    expect(screen.queryByRole("dialog", { name: "Document Assistant" })).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: "a" });
    expect(await screen.findByRole("dialog", { name: "Document Assistant" })).toBeInTheDocument();
  });

  it("does not trigger shortcuts behind an open dialog", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Listening history" }));
    expect(await screen.findByRole("dialog", { name: "Document History" })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "a" });
    expect(screen.queryByRole("dialog", { name: "Document Assistant" })).not.toBeInTheDocument();
  });
});

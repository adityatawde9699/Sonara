import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

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

  it("labels recent files from their names instead of assuming every session is a PDF", () => {
    localStorage.setItem("sonara_recent_documents", JSON.stringify([
      {
        sourceName: "Imported-notes.docx",
        sourceSha256: "legacy-docx-session",
        voice: "en_US-ryan-medium",
        chunksCount: 12,
        totalDurationSeconds: 540,
        lastListenedAt: Date.now(),
      },
    ]));

    render(<App />);

    expect(screen.getByText("DOCX")).toBeInTheDocument();
    expect(screen.getByText("Imported-notes.docx")).toBeInTheDocument();
    localStorage.removeItem("sonara_recent_documents");
  });

  it("opens settings and keyboard shortcuts from their visible controls", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(await screen.findByRole("dialog", { name: "Audio & Engine Settings" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close settings dialog" }));
    fireEvent.click(screen.getByRole("button", { name: "Open keyboard shortcuts guide" }));
    expect(await screen.findByRole("dialog", { name: "Keyboard Shortcuts" })).toBeInTheDocument();
  });

  it("searches recent documents and persists favorite filtering in the library", () => {
    localStorage.setItem("sonara_recent_documents", JSON.stringify([
      { sourceName: "Field Notes.pdf", sourceSha256: "field-notes", voice: "voice", chunksCount: 8, totalDurationSeconds: 600, lastListenedAt: 1000 },
      { sourceName: "Annual Review.docx", sourceSha256: "annual-review", voice: "voice", chunksCount: 12, totalDurationSeconds: 900, lastListenedAt: 2000 },
    ]));
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /My Library/ }));
    expect(screen.getByText("Field Notes.pdf")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search your library" }), { target: { value: "annual" } });
    expect(screen.getByText("Annual Review.docx")).toBeInTheDocument();
    expect(screen.queryByText("Field Notes.pdf")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search your library" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to favorites: Field Notes.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: "Favorites" }));
    expect(screen.getByText("Field Notes.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Annual Review.docx")).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("sonara_favorites") || "[]")).toContain("field-notes");
    localStorage.removeItem("sonara_recent_documents");
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
});

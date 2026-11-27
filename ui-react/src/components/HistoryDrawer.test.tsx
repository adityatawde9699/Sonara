import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { HistoryDrawer } from "./HistoryDrawer";

describe("HistoryDrawer component", () => {
  it("renders empty state when there are no recent documents", () => {
    render(
      <HistoryDrawer
        isOpen={true}
        onClose={vi.fn()}
        recentDocs={[]}
        onClearHistory={vi.fn()}
      />
    );

    expect(screen.getByText("No recent documents yet.")).toBeInTheDocument();
  });

  it("renders list of recent documents with duration and passages", () => {
    const docs = [
      {
        sourceName: "paper.pdf",
        sourceSha256: "hash123",
        voice: "en_US-john-medium",
        chunksCount: 8,
        totalDurationSeconds: 125,
        lastListenedAt: Date.now() - 5000,
        engine: "Piper",
        available: true,
        createdAt: 0,
        pageCount: null,
        language: null,
        complete: true,
      },
    ];

    render(
      <HistoryDrawer
        isOpen={true}
        onClose={vi.fn()}
        recentDocs={docs}
        onClearHistory={vi.fn()}
      />
    );

    expect(screen.getByText("paper.pdf")).toBeInTheDocument();
    expect(screen.getByText("8 passages")).toBeInTheDocument();
    expect(screen.getByText("2:05")).toBeInTheDocument();
    expect(screen.getByText("Just now")).toBeInTheDocument();
  });

  it("calls onClearHistory when Clear history button is clicked", () => {
    const onClearHistory = vi.fn();
    const docs = [
      {
        sourceName: "paper.pdf",
        sourceSha256: "hash123",
        voice: "en_US-john-medium",
        chunksCount: 8,
        totalDurationSeconds: 125,
        lastListenedAt: Date.now(),
        engine: "Piper",
        available: true,
        createdAt: 0,
        pageCount: null,
        language: null,
        complete: true,
      },
    ];

    render(
      <HistoryDrawer
        isOpen={true}
        onClose={vi.fn()}
        recentDocs={docs}
        onClearHistory={onClearHistory}
      />
    );

    fireEvent.click(screen.getByText("Clear history"));
    expect(onClearHistory).toHaveBeenCalledTimes(1);
  });

  it("opens available documents and disables ones whose file is gone", () => {
    const onOpenDocument = vi.fn();
    const base = {
      voice: "v", engine: "Piper", chunksCount: 1, totalDurationSeconds: 10, lastListenedAt: Date.now(),
      createdAt: 0, pageCount: null, language: null, complete: true,
    };
    render(
      <HistoryDrawer
        isOpen={true}
        onClose={vi.fn()}
        onClearHistory={vi.fn()}
        onOpenDocument={onOpenDocument}
        currentSha256="current"
        recentDocs={[
          { ...base, sourceName: "now.pdf", sourceSha256: "current", available: true },
          { ...base, sourceName: "old.txt", sourceSha256: "old", available: true },
          { ...base, sourceName: "gone.md", sourceSha256: "gone", available: false },
        ]}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Continue now.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: "Open old.txt" }));
    expect(onOpenDocument.mock.calls).toEqual([["current"], ["old"]]);
    expect(screen.getByRole("button", { name: "Open gone.md" })).toBeDisabled();
    expect(screen.getByText("File moved or deleted")).toBeInTheDocument();
  });
});

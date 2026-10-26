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
});

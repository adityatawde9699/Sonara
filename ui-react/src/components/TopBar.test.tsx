import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TopBar } from "./TopBar";

describe("TopBar component", () => {
  it("renders brand name and local core-processing badge", () => {
    render(
      <TopBar
        historyCount={0}
        onOpenHistory={vi.fn()}
        onOpenSettings={vi.fn()}
        onOpenShortcuts={vi.fn()}
      />
    );

    expect(screen.getByText("Sonara")).toBeInTheDocument();
    expect(screen.getByText("Core runs here")).toBeInTheDocument();
  });

  it("displays history count badge when count > 0", () => {
    const { rerender } = render(
      <TopBar
        historyCount={0}
        onOpenHistory={vi.fn()}
        onOpenSettings={vi.fn()}
        onOpenShortcuts={vi.fn()}
      />
    );
    expect(screen.queryByText("3")).not.toBeInTheDocument();

    rerender(
      <TopBar
        historyCount={3}
        onOpenHistory={vi.fn()}
        onOpenSettings={vi.fn()}
        onOpenShortcuts={vi.fn()}
      />
    );
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("invokes callbacks on button clicks", () => {
    const onOpenHistory = vi.fn();
    const onOpenSettings = vi.fn();
    const onOpenShortcuts = vi.fn();

    render(
      <TopBar
        historyCount={2}
        onOpenHistory={onOpenHistory}
        onOpenSettings={onOpenSettings}
        onOpenShortcuts={onOpenShortcuts}
      />
    );

    fireEvent.click(screen.getByTitle("Recent documents"));
    expect(onOpenHistory).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTitle("Settings & Audio Specs"));
    expect(onOpenSettings).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTitle("Shortcuts (?)"));
    expect(onOpenShortcuts).toHaveBeenCalledTimes(1);
  });
});

import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { isModalDialogOpen, useModalDialog } from "./useModalDialog";

function Dialog({ name, isOpen, onClose }: { name: string; isOpen: boolean; onClose: () => void }) {
  const ref = useModalDialog<HTMLDivElement>(isOpen, onClose);
  if (!isOpen) return null;
  return (
    <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={name}>
      <button type="button">{name} first</button>
      <button type="button">{name} last</button>
    </div>
  );
}

function Harness() {
  const [outer, setOuter] = useState(false);
  const [inner, setInner] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOuter(true)}>Open outer</button>
      <Dialog name="Outer" isOpen={outer} onClose={() => setOuter(false)} />
      {outer && <button type="button" onClick={() => setInner(true)}>Open inner</button>}
      <Dialog name="Inner" isOpen={inner} onClose={() => setInner(false)} />
    </>
  );
}

describe("useModalDialog", () => {
  it("moves focus into the dialog and returns it to the opener on close", () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open outer" });
    opener.focus();
    fireEvent.click(opener);
    expect(screen.getByRole("button", { name: "Outer first" })).toHaveFocus();
    expect(isModalDialogOpen()).toBe(true);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Outer" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(isModalDialogOpen()).toBe(false);
  });

  it("closes only the topmost dialog per Escape press", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Open outer" }));
    fireEvent.click(screen.getByRole("button", { name: "Open inner" }));
    expect(screen.getByRole("dialog", { name: "Inner" })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Inner" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Outer" })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Outer" })).not.toBeInTheDocument();
  });

  it("keeps Tab focus inside the dialog", () => {
    const onClose = vi.fn();
    render(<Dialog name="Solo" isOpen onClose={onClose} />);
    const first = screen.getByRole("button", { name: "Solo first" });
    const last = screen.getByRole("button", { name: "Solo last" });

    act(() => last.focus());
    fireEvent.keyDown(window, { key: "Tab" });
    expect(first).toHaveFocus();

    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
    expect(onClose).not.toHaveBeenCalled();
  });
});

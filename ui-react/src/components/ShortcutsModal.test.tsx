import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ShortcutsModal } from "./ShortcutsModal";

describe("ShortcutsModal component", () => {
  it("does not render when isOpen is false", () => {
    const { container } = render(<ShortcutsModal isOpen={false} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders shortcuts table when isOpen is true", () => {
    render(<ShortcutsModal isOpen={true} onClose={vi.fn()} />);

    expect(screen.getByText("Keyboard Shortcuts")).toBeInTheDocument();
    expect(screen.getByText("Space / K")).toBeInTheDocument();
    expect(screen.getByText("Play or pause narration")).toBeInTheDocument();
  });

  it("calls onClose when clicking close button or Got it", () => {
    const onClose = vi.fn();
    render(<ShortcutsModal isOpen={true} onClose={onClose} />);

    fireEvent.click(screen.getByLabelText("Close shortcuts dialog"));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText("Got it"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("calls onClose on Escape key press", () => {
    const onClose = vi.fn();
    render(<ShortcutsModal isOpen={true} onClose={onClose} />);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

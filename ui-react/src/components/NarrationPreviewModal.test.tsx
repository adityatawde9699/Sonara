import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NarrationPreviewModal } from "./NarrationPreviewModal";
import type { NarrationPreview, NarrationPreviewChange } from "../lib/tauri";

function change(overrideId: string, text: string, replacement: string, start: number): NarrationPreviewChange {
  return { overrideId, sourceTerm: text, matchedSourceText: text, replacement, sourceStart: start, sourceEnd: start + text.length };
}

const preview: NarrationPreview = {
  sourceName: "paper.pdf",
  language: "en_US",
  totalUnits: 5,
  units: [
    {
      order: 0,
      sourceText: "Dr. Ada measures 3 cm.",
      spokenText: "Doctor Ada measures 3 centimeters.",
      changes: [
        change("abbr-dr", "Dr.", "Doctor", 0),
        change("unit-cm", "cm", "centimeters", 19),
      ],
    },
    { order: 1, sourceText: "[1]", spokenText: "", changes: [change("cite", "[1]", "", 0)] },
  ],
};

describe("NarrationPreviewModal", () => {
  it("renders nothing while closed", () => {
    const { container } = render(<NarrationPreviewModal isOpen={false} onClose={vi.fn()} preview={preview} loading={false} error="" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows source and spoken text with the changes between them", () => {
    render(<NarrationPreviewModal isOpen onClose={vi.fn()} preview={preview} loading={false} error="" />);
    expect(screen.getByRole("dialog", { name: "What Sonara will read" })).toBeInTheDocument();
    expect(screen.getByText("Dr. Ada measures 3 cm.")).toBeInTheDocument();
    expect(screen.getByText("Doctor Ada measures 3 centimeters.")).toBeInTheDocument();
    expect(screen.getByText("en-US")).toBeInTheDocument();
    expect(screen.getByText("3 spoken-text changes in preview")).toBeInTheDocument();
    // An empty replacement is shown as omitted rather than as a blank.
    expect(screen.getByText(/omitted/)).toBeInTheDocument();
    expect(screen.getByText("Showing the first 2 of 5 speech units.")).toBeInTheDocument();
  });

  it("reports loading and errors accessibly", () => {
    const { rerender } = render(<NarrationPreviewModal isOpen onClose={vi.fn()} preview={null} loading error="" />);
    expect(screen.getByRole("status")).toHaveTextContent("Preparing local preview");
    rerender(<NarrationPreviewModal isOpen onClose={vi.fn()} preview={null} loading={false} error="Extraction failed." />);
    expect(screen.getByRole("alert")).toHaveTextContent("Extraction failed.");
  });

  it("closes from Escape, the close button, Done, and the backdrop but not from inside the card", () => {
    const onClose = vi.fn();
    render(<NarrationPreviewModal isOpen onClose={onClose} preview={preview} loading={false} error="" />);
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close narration preview" }));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    fireEvent.click(screen.getByText("Dr. Ada measures 3 cm."));
    expect(onClose).toHaveBeenCalledTimes(3);
    fireEvent.click(screen.getByRole("dialog").parentElement as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(4);
  });
});

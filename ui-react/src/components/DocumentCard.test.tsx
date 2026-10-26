import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DocumentCard } from "./DocumentCard";

describe("DocumentCard component", () => {
  it("renders idle state with 'No document selected'", () => {
    render(
      <DocumentCard
        phase="idle"
        documentName=""
        statusText="Your file stays on this device."
        errorText=""
        disabled={false}
        onChoose={vi.fn()}
        onStartSynthesis={vi.fn()}
        onCancelSynthesis={vi.fn()}
      />
    );

    expect(screen.getByText("No document selected")).toBeInTheDocument();
    expect(screen.getByText("Your file stays on this device.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Choose document/i })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /Prepare speech/i })).not.toBeInTheDocument();
  });

  it("renders selected state with 'Prepare speech' button", () => {
    const onStartSynthesis = vi.fn();
    render(
      <DocumentCard
        phase="selected"
        documentName="test.pdf"
        statusText="Ready to prepare speech"
        errorText=""
        disabled={false}
        onChoose={vi.fn()}
        onStartSynthesis={onStartSynthesis}
        onCancelSynthesis={vi.fn()}
      />
    );

    expect(screen.getByText("test.pdf")).toBeInTheDocument();
    const startBtn = screen.getByRole("button", { name: /Prepare speech/i });
    expect(startBtn).toBeInTheDocument();

    fireEvent.click(startBtn);
    expect(onStartSynthesis).toHaveBeenCalledTimes(1);
  });

  it("renders synthesizing state with progress indicator and cancel button", () => {
    const onCancelSynthesis = vi.fn();
    render(
      <DocumentCard
        phase="synthesizing"
        documentName="test.pdf"
        statusText="Preparing speech with local Piper voice…"
        errorText=""
        disabled={false}
        onChoose={vi.fn()}
        onStartSynthesis={vi.fn()}
        onCancelSynthesis={onCancelSynthesis}
      />
    );

    expect(screen.getAllByText("Preparing speech with local Piper voice…").length).toBe(2);
    const cancelBtn = screen.getByRole("button", { name: /Cancel/i });
    expect(cancelBtn).toBeInTheDocument();

    fireEvent.click(cancelBtn);
    expect(onCancelSynthesis).toHaveBeenCalledTimes(1);
  });

  it("displays error messages with error styling", () => {
    render(
      <DocumentCard
        phase="idle"
        documentName=""
        statusText="Ready"
        errorText="Corrupt PDF header"
        disabled={false}
        onChoose={vi.fn()}
        onStartSynthesis={vi.fn()}
        onCancelSynthesis={vi.fn()}
      />
    );

    const errorMsg = screen.getByText("Corrupt PDF header");
    expect(errorMsg).toBeInTheDocument();
    expect(errorMsg).toHaveClass("error");
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReaderPanel } from "./ReaderPanel";
import { getDocumentText } from "../lib/tauri";

vi.mock("../lib/tauri", () => ({ getDocumentText: vi.fn() }));

const documentText = Array.from({ length: 35 }, (_, index) =>
  index === 30 ? "A later paragraph about narration." : `Paragraph ${index + 1}.`
).join("\n\n");

describe("ReaderPanel", () => {
  beforeEach(() => {
    vi.mocked(getDocumentText).mockReset();
    vi.mocked(getDocumentText).mockResolvedValue(documentText);
  });

  it("loads locally extracted text and pages long documents", async () => {
    render(<ReaderPanel sourceName="report.pdf" sourceSha256="hash-1" />);

    expect(await screen.findByText("Paragraph 1.")).toBeInTheDocument();
    expect(screen.getByText("35 paragraphs")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("A later paragraph about narration.")).toBeInTheDocument();
    expect(screen.getByText("Section 2 of 2")).toBeInTheDocument();
    expect(screen.getByText("Locally extracted text · audio position is not synced to paragraphs")).toBeInTheDocument();
  });

  it("searches the extracted text and reports no matches", async () => {
    render(<ReaderPanel sourceName="report.pdf" sourceSha256="hash-2" />);
    await screen.findByText("Paragraph 1.");
    const search = screen.getByRole("textbox", { name: "Search in document" });
    fireEvent.change(search, { target: { value: "narration" } });

    expect(await screen.findByText("A later paragraph about narration.")).toBeInTheDocument();
    expect(screen.getByText("1", { selector: ".reader-match-count" })).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "not present" } });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("No matches in this document."));
  });

  it("offers retry when text extraction fails", async () => {
    vi.mocked(getDocumentText).mockRejectedValueOnce(new Error("Text extraction failed."));
    render(<ReaderPanel sourceName="report.pdf" sourceSha256="hash-3" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Text extraction failed.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(getDocumentText).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Paragraph 1.")).toBeInTheDocument();
  });
});

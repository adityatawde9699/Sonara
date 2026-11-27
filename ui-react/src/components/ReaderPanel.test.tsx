import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReaderPanel } from "./ReaderPanel";
import { type FrontendChunk, getDocumentText, getReaderDocument } from "../lib/tauri";
import { splitAtCodePoints } from "../lib/readAlong";

vi.mock("../lib/tauri", () => ({ getDocumentText: vi.fn(), getReaderDocument: vi.fn() }));

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
    expect(screen.getByText("Locally extracted text · prepare speech again to highlight along with the audio")).toBeInTheDocument();
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

describe("ReaderPanel read-along", () => {
  const blocks = Array.from({ length: 40 }, (_, index) => ({
    id: `b-${index}`,
    kind: "paragraph",
    text: index === 33 ? "First sentence here. Second sentence is spoken now." : `Block ${index + 1}.`,
  }));
  const chunks: FrontendChunk[] = [
    { durationSeconds: 2, pauseAfterMs: 0, source: { blockId: "b-0", start: 0, end: 8 } },
    { durationSeconds: 2, pauseAfterMs: 0, source: { blockId: "b-33", start: 0, end: 21 } },
    { durationSeconds: 2, pauseAfterMs: 0, source: { blockId: "b-33", start: 21, end: 51 } },
  ];

  beforeEach(() => {
    vi.mocked(getReaderDocument).mockReset();
    vi.mocked(getReaderDocument).mockResolvedValue({ sourceSha256: "h", blocks });
    vi.mocked(getDocumentText).mockReset();
  });

  it("highlights the spoken passage and follows it to its page", async () => {
    const { rerender } = render(<ReaderPanel sourceName="r.pdf" sourceSha256="h" chunks={chunks} activeChunk={0} />);
    expect(await screen.findByText("Block 1.", { selector: "mark" })).toBeInTheDocument();
    expect(getDocumentText).not.toHaveBeenCalled();

    rerender(<ReaderPanel sourceName="r.pdf" sourceSha256="h" chunks={chunks} activeChunk={2} />);
    const spoken = await screen.findByText("Second sentence is spoken now.", { selector: "mark" });
    expect(spoken).toHaveAttribute("aria-current", "true");
    expect(spoken.closest("p")).toHaveClass("is-speaking");
    expect(screen.getByText("Section 2 of 2")).toBeInTheDocument();
  });

  it("stops following after a manual page turn until re-enabled", async () => {
    const { rerender } = render(<ReaderPanel sourceName="r.pdf" sourceSha256="h" chunks={chunks} activeChunk={0} />);
    await screen.findByText("Block 1.", { selector: "mark" });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    rerender(<ReaderPanel sourceName="r.pdf" sourceSha256="h" chunks={chunks} activeChunk={1} />);
    expect(screen.getByText("Section 1 of 2")).toBeInTheDocument();
    const follow = screen.getByRole("button", { name: "Follow along" });
    expect(follow).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(follow);
    expect(await screen.findByText("Section 2 of 2")).toBeInTheDocument();
  });

  it("starts listening from a paragraph's first passage", async () => {
    const onPlay = vi.fn();
    render(<ReaderPanel sourceName="r.pdf" sourceSha256="h" chunks={chunks} activeChunk={0} onPlayFromChunk={onPlay} />);
    await screen.findByText("Block 1.", { selector: "mark" });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(await screen.findByRole("button", { name: "Listen from paragraph 34" }));
    expect(onPlay).toHaveBeenCalledWith(1);
    // Paragraphs without a passage have no play button.
    expect(screen.queryByRole("button", { name: "Listen from paragraph 35" })).not.toBeInTheDocument();
  });

  it("shows a cited span on its page and offers to listen from it", async () => {
    vi.mocked(getReaderDocument).mockResolvedValue({
      sourceSha256: "h",
      pageLabel: "page",
      blocks: blocks.map((block, index) => ({ ...block, page: index < 30 ? 1 : 2 })),
    });
    const onPlay = vi.fn();
    render(
      <ReaderPanel
        sourceName="r.pdf" sourceSha256="h" chunks={chunks} activeChunk={0} onPlayFromChunk={onPlay}
        jumpTarget={{ blockId: "b-33", start: 21, end: 51, key: 1 }}
      />
    );
    const cited = await screen.findByText("Second sentence is spoken now.", { selector: "mark.reader-cited" });
    expect(cited.closest("p")).toHaveClass("is-cited");
    expect(screen.getByText("Section 2 of 2")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Showing the cited passage · page 2");
    expect(screen.getByText("Page 2")).toHaveClass("reader-page-marker");
    // The passage that speaks offset 21 of block 34 is passage 3.
    fireEvent.click(screen.getByRole("button", { name: "Listen from here" }));
    expect(onPlay).toHaveBeenCalledWith(2);
    expect(screen.queryByText("Showing the cited passage", { exact: false })).not.toBeInTheDocument();
  });

  it("says so when a cited block is not in the document", async () => {
    render(<ReaderPanel sourceName="r.pdf" sourceSha256="h" chunks={chunks} jumpTarget={{ blockId: "gone", start: 0, end: 1, key: 1 }} />);
    expect(await screen.findByText(/cited passage is not in this document/)).toBeInTheDocument();
  });

  it("falls back to plain text when the extracted blocks are unavailable", async () => {
    vi.mocked(getReaderDocument).mockRejectedValueOnce(new Error("missing"));
    vi.mocked(getDocumentText).mockResolvedValueOnce("Plain one.\n\nPlain two.");
    render(<ReaderPanel sourceName="r.pdf" sourceSha256="h" chunks={chunks} activeChunk={0} />);
    expect(await screen.findByText("Plain one.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Follow along" })).not.toBeInTheDocument();
  });

  it("slices offsets by code point, not UTF-16 unit", () => {
    expect(splitAtCodePoints("ab😀cd", 2, 3)).toEqual(["ab", "😀", "cd"]);
    expect(splitAtCodePoints("abcd", 1, 3)).toEqual(["a", "bc", "d"]);
  });
});

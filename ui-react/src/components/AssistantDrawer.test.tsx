import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AssistantDrawer } from "./AssistantDrawer";
import * as tauri from "../lib/tauri";

vi.mock("../lib/tauri", async () => {
  const actual = await vi.importActual<typeof import("../lib/tauri")>("../lib/tauri");
  return {
    ...actual,
    loadStoredLlmConfig: vi.fn().mockReturnValue({
      provider: "ollama",
      endpoint: "http://localhost:11434/v1",
      model: "llama3.2",
      apiKey: "",
      temperature: 0.7,
      maxTokens: 1024,
    }),
    llmChat: vi.fn().mockResolvedValue({
      ok: true,
      answer: "This is an answer from the assistant.",
    }),
    llmSummarize: vi.fn().mockResolvedValue({
      ok: true,
      summary: "This is an executive summary of the document.",
    }),
  };
});

describe("AssistantDrawer component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not render when isOpen is false", () => {
    const { container } = render(
      <AssistantDrawer
        isOpen={false}
        onClose={vi.fn()}
        session={null}
        documentName="test.pdf"
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders header, model badge, document name, chips, and empty state when open", async () => {
    render(
      <AssistantDrawer
        isOpen={true}
        onClose={vi.fn()}
        session={null}
        documentName="sample-story.pdf"
      />
    );

    expect(screen.getByRole("heading", { name: "Assistant" })).toBeInTheDocument();
    expect(screen.getByText("llama3.2")).toBeInTheDocument();
    expect(screen.getByText("sample-story.pdf")).toBeInTheDocument();
    expect(screen.getByText("📋 Full Summary")).toBeInTheDocument();
    expect(screen.getByText("💡 Key Takeaways")).toBeInTheDocument();
    expect(screen.getByText("🔍 Explain Concepts")).toBeInTheDocument();
    expect(screen.getByText("Ask about this document")).toBeInTheDocument();
  });

  it("triggers llmSummarize on quick action chip click and displays summary", async () => {
    render(
      <AssistantDrawer
        isOpen={true}
        onClose={vi.fn()}
        session={null}
        documentName="sample-story.pdf"
      />
    );

    const summaryChip = screen.getByText("📋 Full Summary");
    fireEvent.click(summaryChip);

    await waitFor(() => {
      expect(tauri.llmSummarize).toHaveBeenCalledWith(
        expect.anything(),
        "summary"
      );
      expect(
        screen.getByText("This is an executive summary of the document.")
      ).toBeInTheDocument();
    });
  });

  it("sends user message and displays assistant response", async () => {
    render(
      <AssistantDrawer
        isOpen={true}
        onClose={vi.fn()}
        session={null}
        documentName="sample-story.pdf"
      />
    );

    const textarea = screen.getByPlaceholderText(/Ask a question about this document/i);
    fireEvent.change(textarea, { target: { value: "Who is the main character?" } });

    const sendBtn = screen.getByTitle("Send message");
    fireEvent.click(sendBtn);

    expect(screen.getByText("Who is the main character?")).toBeInTheDocument();

    await waitFor(() => {
      expect(tauri.llmChat).toHaveBeenCalledWith(
        expect.anything(),
        "Who is the main character?",
        expect.any(Array)
      );
      expect(
        screen.getByText("This is an answer from the assistant.")
      ).toBeInTheDocument();
    });
  });

  it("calls onClose when clicking close button", async () => {
    const onClose = vi.fn();
    render(
      <AssistantDrawer
        isOpen={true}
        onClose={onClose}
        session={null}
        documentName="sample-story.pdf"
      />
    );
    fireEvent.click(screen.getByLabelText("Close document assistant"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("turns cited passage labels into chips that open the reader", async () => {
    const citation: tauri.Citation = {
      label: "Passage 2",
      passageIndex: 1,
      page: 12,
      pageLabel: "page",
      spans: [{ blockId: "p12-b3", start: 4, end: 40 }],
      excerpt: "The probe launched at dawn.",
    };
    vi.mocked(tauri.llmChat).mockResolvedValueOnce({
      ok: true,
      answer: "It launched at dawn [Passage 2]. Also [Passage 7].",
      citations: [citation],
    });
    const onOpenCitation = vi.fn();
    render(
      <AssistantDrawer isOpen onClose={vi.fn()} session={null} documentName="probe.pdf" onOpenCitation={onOpenCitation} />
    );
    fireEvent.change(screen.getByPlaceholderText(/Ask a question/i), { target: { value: "When?" } });
    fireEvent.click(screen.getByTitle("Send message"));

    const chip = await screen.findByRole("button", { name: "Show Passage 2, p. 12, in the reader" });
    expect(chip).toHaveTextContent("p. 12");
    expect(chip).toHaveAttribute("title", "The probe launched at dawn.");
    // A label for a passage the model was not given stays plain text.
    expect(screen.getByText("[Passage 7]")).toBeInTheDocument();
    fireEvent.click(chip);
    expect(onOpenCitation).toHaveBeenCalledWith(citation);
  });

  it("stops an answer in progress and notes it without an error", async () => {
    let finish: (value: tauri.LlmChatResult) => void = () => {};
    vi.mocked(tauri.llmChat).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    const cancel = vi.spyOn(tauri, "llmCancel").mockImplementation(async () => {
      finish({ ok: false, error: tauri.LLM_CANCELLED });
      return true;
    });
    render(<AssistantDrawer isOpen onClose={vi.fn()} session={null} documentName="d.pdf" />);
    fireEvent.change(screen.getByPlaceholderText(/Ask a question/i), { target: { value: "Long question" } });
    fireEvent.click(screen.getByTitle("Send message"));

    fireEvent.click(await screen.findByRole("button", { name: "Stop the answer" }));
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("note")).toHaveTextContent("Stopped.");
    expect(screen.queryByText(/Unable to complete request/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send message" })).toBeInTheDocument();
  });
});

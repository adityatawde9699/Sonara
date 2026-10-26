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
    getDocumentText: vi.fn().mockResolvedValue("Sample document text for test."),
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

    expect(screen.getByText("Document Assistant")).toBeInTheDocument();
    expect(screen.getByText("llama3.2")).toBeInTheDocument();
    expect(screen.getByText("sample-story.pdf")).toBeInTheDocument();
    expect(screen.getByText("📋 Full Summary")).toBeInTheDocument();
    expect(screen.getByText("💡 Key Takeaways")).toBeInTheDocument();
    expect(screen.getByText("🔍 Explain Concepts")).toBeInTheDocument();
    expect(screen.getByText("Ask anything about your document")).toBeInTheDocument();
    await waitFor(() => expect(tauri.getDocumentText).toHaveBeenCalled());
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
        "Sample document text for test.",
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
        "Sample document text for test.",
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
    await waitFor(() => expect(tauri.getDocumentText).toHaveBeenCalled());

    fireEvent.click(screen.getByLabelText("Close document assistant"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

import { type FC, useState, useEffect, useRef } from "react";
import { useModalDialog } from "../hooks/useModalDialog";
import {
  type Citation,
  type FrontendSession,
  type LlmConfig,
  type ChatMessage,
  LLM_CANCELLED,
  citationChipLabel,
  loadStoredLlmConfig,
  llmCancel,
  llmChat,
  llmSummarize,
} from "../lib/tauri";
import { Check, Copy, SendHorizontal, Settings, Square, X } from "lucide-react";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  session: FrontendSession | null;
  documentName?: string;
  onOpenSettings?: () => void;
  /** Show a cited passage in the reader; absent when the reader is unavailable. */
  onOpenCitation?: (citation: Citation) => void;
}

interface MessageItem {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
  /** Passages the answer cites, keyed by one-based passage number. */
  citations?: Map<number, Citation>;
}

const PASSAGE_LABEL = /(\[Passages?\s+\d+(?:\s*(?:,|and|&|-|–)\s*\d+)*\])/i;

function stripThinking(raw: string): string {
  if (!raw) return "";
  let text = raw.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
  if (text.includes("<think>")) {
    const before = text.split(/<think>/i)[0].trim();
    text = before ? before : text.replace(/<\/?think>/gi, "").trim();
  }
  return text.replace(/<\/?think>/gi, "").trim();
}

export const AssistantDrawer: FC<Props> = ({
  isOpen,
  onClose,
  session,
  documentName,
  onOpenSettings,
  onOpenCitation,
}) => {
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isStopping, setIsStopping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const dialogRef = useModalDialog<HTMLElement>(isOpen, onClose);

  const llmConfig: LlmConfig = loadStoredLlmConfig();
  const docTitle = documentName || session?.sourceName || "Active Document";

  // Scroll to bottom when messages update
  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView?.({ behavior: "smooth" });
    }
  }, [messages, isLoading, isOpen]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen) {
      const timer = setTimeout(() => inputRef.current?.focus(), 150);
      return () => clearTimeout(timer);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  /** A stopped request is a note, not an error. */
  const stoppedNote = (): MessageItem => ({
    id: `msg-${Date.now()}-stop`,
    role: "system",
    content: "Stopped.",
    timestamp: Date.now(),
  });

  const handleStop = async () => {
    setIsStopping(true);
    setStatusMessage("Stopping…");
    try {
      await llmCancel();
    } catch {
      // The request's own error is shown when it returns.
    }
  };

  const handleSend = async (userPrompt?: string) => {
    const question = (userPrompt ?? input).trim();
    if (!question || isLoading) return;

    const userMsg: MessageItem = {
      id: `msg-${Date.now()}-u`,
      role: "user",
      content: question,
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMsg]);
    if (!userPrompt) setInput("");
    setIsLoading(true);
    setStatusMessage(null);

    // Build chat history for context
    const history: ChatMessage[] = messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));

    try {
      const res = await llmChat(llmConfig, question, history);
      if (res.ok && res.answer) {
        const assistantMsg: MessageItem = {
          id: `msg-${Date.now()}-a`,
          role: "assistant",
          content: res.answer,
          timestamp: Date.now(),
          citations: new Map((res.citations ?? []).map((citation) => [citation.passageIndex + 1, citation])),
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } else if (res.error === LLM_CANCELLED) {
        setMessages((prev) => [...prev, stoppedNote()]);
      } else {
        const errMsg = res.error || "No response received from LLM.";
        setMessages((prev) => [
          ...prev,
          {
            id: `msg-${Date.now()}-err`,
            role: "assistant",
            content: `**Unable to complete request**\n\n${errMsg}`,
            timestamp: Date.now(),
          },
        ]);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setMessages((prev) => [
        ...prev,
        msg === LLM_CANCELLED ? stoppedNote() : {
          id: `msg-${Date.now()}-err`,
          role: "assistant",
          content: `**Error communicating with LLM engine**\n\n${msg}`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsLoading(false);
      setIsStopping(false);
      setStatusMessage(null);
    }
  };

  const handleQuickAction = async (mode: "summary" | "takeaways" | "explain_passage") => {
    if (isLoading) return;

    let actionLabel = "Full Summary";
    let promptQuestion = "Generate an executive summary of this document.";
    if (mode === "takeaways") {
      actionLabel = "Key Takeaways";
      promptQuestion = "Extract the top key takeaways and insights.";
    } else if (mode === "explain_passage") {
      actionLabel = "Concept Explanation";
      promptQuestion = "Explain the central concepts of this document in clear language.";
    }

    const userMsg: MessageItem = {
      id: `msg-${Date.now()}-u`,
      role: "user",
      content: promptQuestion,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);
    setStatusMessage(`Generating ${actionLabel.toLowerCase()}…`);

    try {
      const res = await llmSummarize(llmConfig, mode);
      if (res.ok && res.summary) {
        const assistantMsg: MessageItem = {
          id: `msg-${Date.now()}-a`,
          role: "assistant",
          content: res.summary,
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } else if (res.error === LLM_CANCELLED) {
        setMessages((prev) => [...prev, stoppedNote()]);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: `msg-${Date.now()}-err`,
            role: "assistant",
          content: `**Failed to generate ${actionLabel}**\n\n${res.error || "Unknown error"}`,
            timestamp: Date.now(),
          },
        ]);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setMessages((prev) => [
        ...prev,
        msg === LLM_CANCELLED ? stoppedNote() : {
          id: `msg-${Date.now()}-err`,
          role: "assistant",
          content: `**Error**\n\n${msg}`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsLoading(false);
      setIsStopping(false);
      setStatusMessage(null);
    }
  };

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(stripThinking(text)).then(() => {
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    });
  };

  const handleClearHistory = () => {
    setMessages([]);
  };

  /** A passage label as chips for the passages it cites; text when none were sent. */
  const renderCitationLabel = (label: string, key: string, citations?: Map<number, Citation>) => {
    const cited = (label.match(/\d+/g) ?? [])
      .map((number) => citations?.get(Number(number)))
      .filter((citation): citation is Citation => Boolean(citation));
    if (!cited.length) return <span key={key}>{label}</span>;
    return (
      <span key={key} className="citation-group">
        {cited.map((citation) => (
          <button
            key={citation.passageIndex}
            type="button"
            className="citation-chip"
            title={citation.excerpt}
            aria-label={`Show ${citation.label}, ${citationChipLabel(citation)}, in the reader`}
            disabled={!onOpenCitation}
            onClick={() => onOpenCitation?.(citation)}
          >
            {citationChipLabel(citation)}
          </button>
        ))}
      </span>
    );
  };

  // Helper to format text with lightweight Markdown styling
  const renderFormattedContent = (content: string, citations?: Map<number, Citation>) => {
    const renderInlineFormatting = (text: string) => renderInline(text, citations);
    const cleanContent = stripThinking(content);
    const lines = cleanContent.split("\n");
    return lines.map((line, idx) => {
      if (line.startsWith("### ")) {
        return (
          <h4 key={idx} className="md-h4">
            {line.replace("### ", "")}
          </h4>
        );
      }
      if (line.startsWith("## ")) {
        return (
          <h3 key={idx} className="md-h3">
            {line.replace("## ", "")}
          </h3>
        );
      }
      if (line.startsWith("# ")) {
        return (
          <h2 key={idx} className="md-h2">
            {line.replace("# ", "")}
          </h2>
        );
      }
      if (line.startsWith("- ") || line.startsWith("* ")) {
        const itemText = line.substring(2);
        return (
          <div key={idx} className="md-bullet">
            <span className="md-bullet-dot" aria-hidden="true">•</span>
            <span>{renderInlineFormatting(itemText)}</span>
          </div>
        );
      }
      if (/^\d+\.\s/.test(line)) {
        const numMatch = line.match(/^(\d+\.)\s(.*)$/);
        return (
          <div key={idx} className="md-bullet">
            <span className="md-num">{numMatch ? numMatch[1] : ""}</span>
            <span>{renderInlineFormatting(numMatch ? numMatch[2] : line)}</span>
          </div>
        );
      }
      if (line.trim() === "") {
        return <div key={idx} className="md-spacer" />;
      }
      return (
        <p key={idx} className="md-paragraph">
          {renderInlineFormatting(line)}
        </p>
      );
    });
  };

  const renderInline = (text: string, citations?: Map<number, Citation>) => {
    // Basic bold and code rendering, and passage labels as citation chips.
    const parts = text.split(/(\*\*.*?\*\*|`.*?`)/g);
    return parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return <code key={i} className="md-code">{part.slice(1, -1)}</code>;
      }
      return part.split(PASSAGE_LABEL).map((piece, j) =>
        PASSAGE_LABEL.test(piece) ? renderCitationLabel(piece, `${i}-${j}`, citations) : piece,
      );
    });
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <aside
        ref={dialogRef}
        tabIndex={-1}
        className="assistant-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="assistant-title"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="assistant-header">
          <div className="assistant-title-group">
            <div>
              <div className="assistant-title-row">
                <h2 id="assistant-title">Assistant</h2>
                <span className="assistant-model-pill" title={`Provider: ${llmConfig.provider}`}>
                  {llmConfig.model || "llama3.2"}
                </span>
              </div>
              <p className="assistant-doc-name" title={docTitle}>
                {docTitle}
              </p>
            </div>
          </div>
          <div className="assistant-header-actions">
            {onOpenSettings && (
              <button
                type="button"
                className="assistant-settings-btn"
                onClick={onOpenSettings}
                title="Configure LLM Provider & Settings"
                aria-label="Configure LLM Provider"
              >
                <Settings size={16} aria-hidden="true" />
              </button>
            )}
            <button
              type="button"
              className="modal-close-btn"
              onClick={onClose}
              aria-label="Close document assistant"
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Quick Action Chips */}
        <div className="assistant-chips-bar" role="toolbar" aria-label="Quick assistant actions">
          <button
            type="button"
            className="assistant-chip"
            onClick={() => handleQuickAction("summary")}
            disabled={isLoading}
            title="Summarize the entire document into an executive brief"
          >
            📋 Full Summary
          </button>
          <button
            type="button"
            className="assistant-chip"
            onClick={() => handleQuickAction("takeaways")}
            disabled={isLoading}
            title="Extract high-impact key takeaways"
          >
            💡 Key Takeaways
          </button>
          <button
            type="button"
            className="assistant-chip"
            onClick={() => handleQuickAction("explain_passage")}
            disabled={isLoading}
            title="Explain core concepts and terminology in plain English"
          >
            🔍 Explain Concepts
          </button>
        </div>

        {/* Message Stream */}
        <div className="assistant-stream" tabIndex={0} aria-label="Conversation messages">
          {messages.length === 0 ? (
            <div className="assistant-empty">
              <h3>Ask about this document</h3>
              <p>
                Answers come from the assistant provider chosen in Settings.
              </p>
              <div className="assistant-sample-questions">
                <button
                  type="button"
                  className="assistant-sample-btn"
                  onClick={() => handleSend("What is the central premise of this document?")}
                >
                  What is the central premise of this document?
                </button>
                <button
                  type="button"
                  className="assistant-sample-btn"
                  onClick={() => handleSend("Provide a 3-bullet executive summary.")}
                >
                  Provide a 3-bullet executive summary
                </button>
              </div>
            </div>
          ) : (
            messages.map((m) => m.role === "system" ? (
              <p key={m.id} className="assistant-note" role="note">{m.content}</p>
            ) : (
              <div
                key={m.id}
                className={`assistant-msg-row ${m.role === "user" ? "user-row" : "assistant-row"}`}
              >
                <div className={`assistant-bubble ${m.role === "user" ? "user-bubble" : "assistant-bubble-bot"}`}>
                  <div className="bubble-header">
                    <span className="bubble-author">
                      {m.role === "user" ? "You" : "Sonara Assistant"}
                    </span>
                    {m.role === "assistant" && (
                      <button
                        type="button"
                        className="bubble-copy-btn"
                        onClick={() => handleCopy(m.id, m.content)}
                        title="Copy to clipboard"
                        aria-label="Copy assistant answer"
                      >
                        {copiedId === m.id ? <><Check size={16} aria-hidden="true" />Copied</> : <><Copy size={16} aria-hidden="true" />Copy</>}
                      </button>
                    )}
                  </div>
                  <div className="bubble-body">
                    {renderFormattedContent(m.content, m.citations)}
                  </div>
                </div>
              </div>
            ))
          )}

          {isLoading && (
            <div className="assistant-msg-row assistant-row">
              <div className="assistant-bubble assistant-bubble-bot">
                <div className="bubble-header">
                  <span className="bubble-author">Sonara Assistant</span>
                </div>
                <div className="assistant-typing-indicator" aria-label="Thinking">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  {statusMessage && <span className="typing-status-text">{statusMessage}</span>}
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <div className="assistant-input-area">
          {messages.length > 0 && (
            <div className="assistant-input-top-bar">
              <button
                type="button"
                className="assistant-clear-btn"
                onClick={handleClearHistory}
                disabled={isLoading}
              >
                Clear history
              </button>
            </div>
          )}
          <form
            className="assistant-input-form"
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
          >
            <textarea
              ref={inputRef}
              className="assistant-textarea"
              placeholder="Ask a question about this document… (Enter to send, Shift+Enter for new line)"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              rows={2}
              disabled={isLoading}
              aria-label="Ask assistant question"
            />
            {isLoading ? (
              <button
                type="button"
                className="assistant-send-btn assistant-stop-btn"
                onClick={() => void handleStop()}
                disabled={isStopping}
                aria-label="Stop the answer"
                title="Stop"
              >
                <Square size={14} fill="currentColor" aria-hidden="true" />
              </button>
            ) : (
              <button
                type="submit"
                className="assistant-send-btn"
                disabled={!input.trim()}
                aria-label="Send message"
                title="Send message"
              >
                <SendHorizontal size={16} aria-hidden="true" />
              </button>
            )}
          </form>
        </div>
      </aside>
    </div>
  );
};

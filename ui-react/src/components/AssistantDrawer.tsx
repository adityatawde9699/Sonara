import { type FC, useState, useEffect, useRef } from "react";
import {
  type FrontendSession,
  type LlmConfig,
  type ChatMessage,
  loadStoredLlmConfig,
  llmChat,
  llmSummarize,
  getDocumentText,
} from "../lib/tauri";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  session: FrontendSession | null;
  documentName?: string;
  onOpenSettings?: () => void;
}

interface MessageItem {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
}

export const AssistantDrawer: FC<Props> = ({
  isOpen,
  onClose,
  session,
  documentName,
  onOpenSettings,
}) => {
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [docText, setDocText] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const llmConfig: LlmConfig = loadStoredLlmConfig();
  const docTitle = documentName || session?.sourceName || "Active Document";

  // Pre-load document text when drawer is opened
  useEffect(() => {
    if (!isOpen) return;

    let mounted = true;
    getDocumentText()
      .then((text) => {
        if (mounted && text) {
          setDocText(text);
        }
      })
      .catch(() => {
        // Text retrieval will fall back to empty context if not ready
      });

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      mounted = false;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose]);

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
      let context = docText;
      if (!context) {
        try {
          context = await getDocumentText();
          setDocText(context);
        } catch {
          context = "";
        }
      }

      const res = await llmChat(llmConfig, question, context, history);
      if (res.ok && res.answer) {
        const assistantMsg: MessageItem = {
          id: `msg-${Date.now()}-a`,
          role: "assistant",
          content: res.answer,
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
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
        {
          id: `msg-${Date.now()}-err`,
          role: "assistant",
          content: `**Error communicating with LLM engine**\n\n${msg}`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsLoading(false);
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
      let text = docText;
      if (!text) {
        text = await getDocumentText();
        setDocText(text);
      }

      const res = await llmSummarize(llmConfig, text, mode);
      if (res.ok && res.summary) {
        const assistantMsg: MessageItem = {
          id: `msg-${Date.now()}-a`,
          role: "assistant",
          content: res.summary,
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
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
        {
          id: `msg-${Date.now()}-err`,
          role: "assistant",
          content: `**Error**\n\n${msg}`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsLoading(false);
      setStatusMessage(null);
    }
  };

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    });
  };

  const handleClearHistory = () => {
    setMessages([]);
  };

  // Helper to format text with lightweight Markdown styling
  const renderFormattedContent = (content: string) => {
    const lines = content.split("\n");
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

  const renderInlineFormatting = (text: string) => {
    // Basic bold and code rendering
    const parts = text.split(/(\*\*.*?\*\*|`.*?`)/g);
    return parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return <code key={i} className="md-code">{part.slice(1, -1)}</code>;
      }
      return part;
    });
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <aside
        className="assistant-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="assistant-title"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="assistant-header">
          <div className="assistant-title-group">
            <div className="assistant-spark-icon" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2l2.4 7.2L21.6 12l-7.2 2.4L12 21.6l-2.4-7.2L2.4 12l7.2-2.4z" />
              </svg>
            </div>
            <div>
              <div className="assistant-title-row">
                <h2 id="assistant-title">Document Assistant</h2>
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
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
                </svg>
              </button>
            )}
            <button
              type="button"
              className="modal-close-btn"
              onClick={onClose}
              aria-label="Close document assistant"
            >
              ✕
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
              <div className="assistant-empty-spark" aria-hidden="true">AI</div>
              <h3>Ask anything about your document</h3>
              <p>
                Get instant summaries, find key insights, clarify difficult concepts,
                or discuss themes while you listen.
              </p>
              <div className="assistant-sample-questions">
                <button
                  type="button"
                  className="assistant-sample-btn"
                  onClick={() => handleSend("What is the central premise of this document?")}
                >
                  "What is the central premise of this document?"
                </button>
                <button
                  type="button"
                  className="assistant-sample-btn"
                  onClick={() => handleSend("Provide a 3-bullet executive summary.")}
                >
                  "Provide a 3-bullet executive summary."
                </button>
              </div>
            </div>
          ) : (
            messages.map((m) => (
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
                        {copiedId === m.id ? "✓ Copied" : "Copy"}
                      </button>
                    )}
                  </div>
                  <div className="bubble-body">
                    {renderFormattedContent(m.content)}
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
            <button
              type="submit"
              className="assistant-send-btn"
              disabled={!input.trim() || isLoading}
              aria-label="Send message"
              title="Send message"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </form>
        </div>
      </aside>
    </div>
  );
};

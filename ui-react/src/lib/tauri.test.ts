import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  isTauriAvailable,
  pickDocument,
  currentSession,
  startReading,
  previewNarration,
  cancelReading,
  loadProgress,
  saveProgress,
  onSynthesisFinished,
  onSynthesisProgress,
} from "./tauri";

describe("Tauri bindings", () => {
  beforeEach(() => {
    // Reset window mock
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (window as any).__TAURI__;
  });

  it("reports Tauri unavailable when __TAURI__ is missing", () => {
    expect(isTauriAvailable()).toBe(false);
  });

  it("throws clear error when invoking command outside Tauri", async () => {
    await expect(pickDocument()).rejects.toThrow("Tauri APIs are unavailable");
  });

  it("invokes commands correctly when Tauri is present", async () => {
    const mockInvoke = vi.fn().mockResolvedValue({ displayName: "report.docx" });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).__TAURI__ = {
      core: { invoke: mockInvoke },
      event: { listen: vi.fn() },
    };

    expect(isTauriAvailable()).toBe(true);

    const result = await pickDocument();
    expect(mockInvoke).toHaveBeenCalledWith("pick_document", undefined);
    expect(result).toEqual({ displayName: "report.docx" });
  });

  it("supports startReading, cancelReading, currentSession, loadProgress, saveProgress, listVoices", async () => {
    const mockInvoke = vi.fn().mockImplementation((cmd, args) => {
      if (cmd === "start_reading") return Promise.resolve(`job-123-${args?.voice || "default"}`);
      if (cmd === "cancel_reading") return Promise.resolve(true);
      if (cmd === "current_session") return Promise.resolve(null);
      if (cmd === "load_progress") return Promise.resolve({ segment: 2, offsetSeconds: 5 });
      if (cmd === "save_progress") return Promise.resolve();
      if (cmd === "list_voices") return Promise.resolve([{ id: "en_US-ryan-medium", name: "Ryan", quality: "medium", language: "en_US", isDefault: true }]);
      if (cmd === "preview_narration") return Promise.resolve({ units: [], notes: [] });
      return Promise.reject(new Error(`Unknown cmd ${cmd}`));
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).__TAURI__ = {
      core: { invoke: mockInvoke },
      event: { listen: vi.fn() },
    };

    const { listVoices } = await import("./tauri");
    expect(await listVoices()).toEqual([{ id: "en_US-ryan-medium", name: "Ryan", quality: "medium", language: "en_US", isDefault: true }]);
    expect(await startReading("en_US-ryan-medium")).toBe("job-123-en_US-ryan-medium");
    expect(mockInvoke).toHaveBeenCalledWith("start_reading", {
      voice: "en_US-ryan-medium",
      variation: undefined,
      expandDates: false,
      expandCitations: false,
    });
    await previewNarration("en_US-ryan-medium", true, false);
    expect(mockInvoke).toHaveBeenCalledWith("preview_narration", {
      voice: "en_US-ryan-medium",
      expandDates: true,
      expandCitations: false,
    });
    expect(await cancelReading()).toBe(true);
    expect(await currentSession()).toBeNull();
    expect(await loadProgress("hash123")).toEqual({ segment: 2, offsetSeconds: 5 });
    await expect(saveProgress({
      version: 1,
      sourceSha256: "hash123",
      segment: 2,
      offsetSeconds: 5,
      playbackRate: 1.0,
    })).resolves.toBeUndefined();
  });

  it("registers synthesis-finished event handler", async () => {
    const unlisten = vi.fn();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let registeredCallback: any = null;
    const mockListen = vi.fn().mockImplementation((_event, cb) => {
      registeredCallback = cb;
      return Promise.resolve(unlisten);
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).__TAURI__ = {
      core: { invoke: vi.fn() },
      event: { listen: mockListen },
    };

    const handler = vi.fn();
    const cleanup = await onSynthesisFinished(handler);
    expect(mockListen).toHaveBeenCalledWith("synthesis-finished", expect.any(Function));

    // Simulate event payload
    if (typeof registeredCallback === "function") {
      registeredCallback({
        payload: {
          jobId: "123",
          result: { Err: "Missing Piper voice" },
        },
      });
    }

    expect(handler).toHaveBeenCalledWith({
      jobId: "123",
      result: { Err: "Missing Piper voice" },
    });

    cleanup();
    expect(unlisten).toHaveBeenCalled();
  });

  it("registers and calls onSynthesisProgress listener", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let registeredCallback: any = null;
    const unlisten = vi.fn();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).__TAURI__ = {
      event: {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        listen: vi.fn().mockImplementation((event: string, cb: any) => {
          if (event === "synthesis-progress") registeredCallback = cb;
          return Promise.resolve(unlisten);
        }),
      },
    };

    const handler = vi.fn();
    const cleanup = await onSynthesisProgress(handler);

    if (typeof registeredCallback === "function") {
      registeredCallback({
        payload: {
          jobId: "123",
          completedChunks: 3,
          totalChunks: 10,
        },
      });
    }

    expect(handler).toHaveBeenCalledWith({
      jobId: "123",
      completedChunks: 3,
      totalChunks: 10,
    });

    cleanup();
    expect(unlisten).toHaveBeenCalled();
  });

  it("supports LLM commands and storage helpers", async () => {
    const {
      loadStoredLlmConfig,
      saveStoredLlmConfig,
      llmTestConnection,
      llmChat,
      llmSummarize,
      llmEnhanceScript,
      getDocumentText,
    } = await import("./tauri");

    // Local storage persistence
    localStorage.clear();
    const defaultCfg = loadStoredLlmConfig();
    expect(defaultCfg.provider).toBe("ollama");
    expect(defaultCfg.model).toBe("llama3.2");

    saveStoredLlmConfig({
      provider: "openai",
      endpoint: "https://api.openai.com/v1",
      model: "gpt-4o-mini",
      apiKey: "sk-test",
    });
    const loadedCfg = loadStoredLlmConfig();
    expect(loadedCfg.provider).toBe("openai");
    expect(loadedCfg.apiKey).toBe("sk-test");

    // Invoke mock
    const mockInvoke = vi.fn().mockImplementation((cmd, args) => {
      if (cmd === "llm_test_connection") return Promise.resolve({ ok: true, latencyMs: 30 });
      if (cmd === "llm_chat") return Promise.resolve({ ok: true, answer: "Answer for " + args?.question });
      if (cmd === "llm_summarize") return Promise.resolve({ ok: true, summary: "Summary of document" });
      if (cmd === "llm_enhance_script") return Promise.resolve({ ok: true, enhancement: { spokenText: "Spoken", notes: [], suggestedOverrides: [] } });
      if (cmd === "get_document_text") return Promise.resolve("Full document text here");
      return Promise.reject(new Error(`Unknown cmd: ${cmd}`));
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).__TAURI__ = {
      core: { invoke: mockInvoke },
      event: { listen: vi.fn() },
    };

    const testRes = await llmTestConnection(loadedCfg);
    expect(testRes.ok).toBe(true);
    expect(mockInvoke).toHaveBeenCalledWith("llm_test_connection", { config: loadedCfg });

    const chatRes = await llmChat(loadedCfg, "What is this doc?");
    expect(chatRes.ok).toBe(true);
    expect(chatRes.answer).toBe("Answer for What is this doc?");

    const sumRes = await llmSummarize(loadedCfg, "doc text", "summary");
    expect(sumRes.ok).toBe(true);
    expect(sumRes.summary).toBe("Summary of document");

    const enhRes = await llmEnhanceScript(loadedCfg, "raw text");
    expect(enhRes.ok).toBe(true);
    expect(enhRes.enhancement?.spokenText).toBe("Spoken");

    const docText = await getDocumentText();
    expect(docText).toBe("Full document text here");
  });
});


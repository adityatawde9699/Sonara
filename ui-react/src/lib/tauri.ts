/**
 * Type-safe bindings for Sonara's Tauri backend commands and events.
 * These types mirror the Rust structs in src-tauri/src/lib.rs.
 */

// ── Types matching Rust backend ──────────────────────────────────────

export interface SelectedDocument {
  displayName: string;
}

/** A prepared document, as recorded by the desktop library. */
export interface LibraryDocument {
  sourceSha256: string;
  sourceName: string;
  voice: string;
  engine: string;
  chunksCount: number;
  totalDurationSeconds: number;
  /** Unix time in milliseconds. */
  lastListenedAt: number;
  /** When the document was first prepared, in Unix milliseconds. */
  createdAt: number;
  pageCount: number | null;
  language: string | null;
  /** False for a document whose audio was only partly prepared. */
  complete: boolean;
  /** False when the source file has been moved or deleted. */
  available: boolean;
}

/** Character offsets of a passage within one extracted document block. */
export interface SourceSpan {
  blockId: string;
  start: number;
  end: number;
}

export interface FrontendChunk {
  durationSeconds: number;
  pauseAfterMs: number;
  /** Absent for sessions prepared before read-along highlighting existed. */
  source?: SourceSpan | null;
  /** The narration unit spoken; absent for sessions from Sonara 1.x. */
  unitId?: string | null;
}

export interface ReaderBlock {
  id: string;
  kind: string;
  text: string;
  /** One-based source page, when the extractor recorded one. */
  page?: number | null;
}

/** "page" for real PDF pages; "section" for the virtual pages of other formats. */
export type PageLabel = "page" | "section";

export interface ReaderDocument {
  sourceSha256: string;
  pageLabel?: PageLabel;
  blocks: ReaderBlock[];
}

export interface FrontendSession {
  sourceName: string;
  sourceSha256: string;
  narrationRulesetVersion: string;
  voice: string;
  engine?: string;
  sampleRate: number;
  channels: number;
  sampleWidthBytes: number;
  audioBaseUrl: string;
  chunks: FrontendChunk[];
}

export interface VoiceInfo {
  id: string;
  name: string;
  quality: string;
  language: string;
  isDefault: boolean;
}

export type PiperVariation = "voice_default" | "less" | "more";
export type SpeechEngine = "piper" | "kokoro";
export type ResourceProfile = "low_resource" | "standard" | "high_performance";

export interface NarrationPreviewChange {
  overrideId: string;
  sourceTerm: string;
  replacement: string;
  matchedSourceText: string;
  sourceStart: number;
  sourceEnd: number;
}

export interface NarrationPreviewUnit {
  order: number;
  sourceText: string;
  spokenText: string;
  changes: NarrationPreviewChange[];
}

export interface NarrationPreview {
  sourceName: string;
  language: string;
  totalUnits: number;
  units: NarrationPreviewUnit[];
}

export const FALLBACK_VOICES: VoiceInfo[] = [
  { id: "en_US-ryan-medium", name: "Ryan (American Male · Natural)", quality: "medium", language: "en_US", isDefault: true },
  { id: "en_US-lessac-medium", name: "Lessac (American Female · Expressive)", quality: "medium", language: "en_US", isDefault: false },
  { id: "en_US-bryce-medium", name: "Bryce (American Male · Narrative)", quality: "medium", language: "en_US", isDefault: false },
  { id: "en_US-john-medium", name: "John (American Male · LibriVox)", quality: "medium", language: "en_US", isDefault: false },
];

export const PROGRESS_VERSION = 2;

export interface Progress {
  version: number;
  sourceSha256: string;
  segment: number;
  offsetSeconds: number;
  playbackRate: number;
  /** The passage's narration unit, so a position survives renumbering. */
  unitId?: string | null;
}

/**
 * The passage a saved position points at: the chunk with the saved unit id
 * when there is one, otherwise the saved index. Returns -1 when neither
 * fits this session.
 */
export function resolveProgressSegment(progress: Progress, chunks: FrontendChunk[]): number {
  if (progress.unitId) {
    const byUnit = chunks.findIndex((chunk) => chunk.unitId === progress.unitId);
    if (byUnit >= 0) return byUnit;
  }
  return progress.segment >= 0 && progress.segment < chunks.length ? progress.segment : -1;
}

export interface SynthesisFinished {
  jobId: string;
  result: { Ok: FrontendSession } | { Err: string };
}

export interface SynthesisProgress {
  jobId: string;
  completedChunks: number;
  totalChunks: number;
  /** Index of the first passage in `newChunks`. */
  firstChunk: number;
  /** Passages that became playable since the previous event. */
  newChunks: FrontendChunk[];
  /** The whole session so far, on the first event that has passages. */
  session?: FrontendSession | null;
}

/** The run being synthesized, for resynchronizing after a missed event. */
export interface StreamingSnapshot {
  jobId: string;
  totalChunks: number;
  session: FrontendSession;
}

// ── Tauri API wrappers ───────────────────────────────────────────────

function getTauriInvoke(): ((cmd: string, args?: Record<string, unknown>) => Promise<unknown>) | null {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const w = window as any;
  return w.__TAURI__?.core?.invoke ?? null;
}

function getTauriListen(): ((event: string, handler: (payload: unknown) => void) => Promise<() => void>) | null {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const w = window as any;
  return w.__TAURI__?.event?.listen ?? null;
}

export function isTauriAvailable(): boolean {
  return getTauriInvoke() !== null && getTauriListen() !== null;
}

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const fn = getTauriInvoke();
  if (!fn) throw new Error("Tauri APIs are unavailable. Start Sonara through the desktop application.");
  return fn(cmd, args) as Promise<T>;
}

// ── Commands ─────────────────────────────────────────────────────────

export async function pickDocument(): Promise<SelectedDocument | null> {
  return invoke<SelectedDocument | null>("pick_document");
}

export async function listLibrary(): Promise<LibraryDocument[]> {
  return invoke<LibraryDocument[]>("list_library");
}

/** Select a library document for narration; the backend supplies its path. */
export async function openLibraryDocument(sourceSha256: string): Promise<SelectedDocument> {
  return invoke<SelectedDocument>("open_library_document", { sourceSha256 });
}

export async function removeLibraryDocument(sourceSha256: string): Promise<void> {
  return invoke<void>("remove_library_document", { sourceSha256 });
}

export async function clearLibrary(): Promise<void> {
  return invoke<void>("clear_library");
}

export async function currentSession(): Promise<FrontendSession | null> {
  return invoke<FrontendSession | null>("current_session");
}

export async function streamingSession(): Promise<StreamingSnapshot | null> {
  return invoke<StreamingSnapshot | null>("streaming_session");
}

export const FALLBACK_KOKORO_VOICES: VoiceInfo[] = [
  { id: "af_sarah", name: "Sarah · US English · female", quality: "Kokoro", language: "US English", isDefault: true },
  { id: "bm_george", name: "George · British English · male", quality: "Kokoro", language: "British English", isDefault: false },
];

/** Kokoro voices with their languages; the backend owns the list. */
export async function listKokoroVoices(): Promise<VoiceInfo[]> {
  if (!isTauriAvailable()) {
    return FALLBACK_KOKORO_VOICES;
  }
  return invoke<VoiceInfo[]>("list_kokoro_voices");
}

// ── Speech model downloads ──────────────────────────────────────────

/** A model the app can download (installers ship without voice models). */
export interface ModelStatus {
  id: string;
  kind: "piper" | "kokoro";
  label: string;
  sizeBytes: number;
  installed: boolean;
}

export interface ModelDownloadProgress {
  model: string;
  received: number;
  total: number;
}

export async function listModels(): Promise<ModelStatus[]> {
  return invoke<ModelStatus[]>("list_models");
}

/** Downloads, verifies and installs a model; resolves once it is installed. */
export async function installModel(model: string): Promise<void> {
  return invoke<void>("install_model", { model });
}

export async function cancelModelDownload(): Promise<boolean> {
  return invoke<boolean>("cancel_model_download");
}

export async function onModelDownloadProgress(
  handler: (payload: ModelDownloadProgress) => void
): Promise<() => void> {
  const listen = getTauriListen();
  if (!listen) throw new Error("Tauri event API is unavailable.");
  return listen("model-download-progress", (event: unknown) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const e = event as any;
    handler(e.payload as ModelDownloadProgress);
  });
}

/** The open document as blocks, matching the passages' source spans. */
export async function getReaderDocument(): Promise<ReaderDocument> {
  return invoke<ReaderDocument>("get_reader_document");
}

export async function listVoices(): Promise<VoiceInfo[]> {
  if (!isTauriAvailable()) {
    return FALLBACK_VOICES;
  }
  return invoke<VoiceInfo[]>("list_voices");
}

export async function startReading(
  voice?: string,
  variation?: PiperVariation,
  expandDates = false,
  expandCitations = false,
  engine: SpeechEngine = "piper",
  resourceProfile: ResourceProfile = "standard"
): Promise<string> {
  const args: Record<string, unknown> = { voice, variation, expandDates, expandCitations, resourceProfile };
  if (engine !== "piper") args.engine = engine;
  return invoke<string>("start_reading", args);
}

export async function previewNarration(
  voice: string,
  expandDates: boolean,
  expandCitations: boolean
): Promise<NarrationPreview> {
  return invoke<NarrationPreview>("preview_narration", { voice, expandDates, expandCitations });
}

export async function cancelReading(): Promise<boolean> {
  return invoke<boolean>("cancel_reading");
}

export async function loadProgress(sourceSha256: string): Promise<Progress | null> {
  return invoke<Progress | null>("load_progress", { sourceSha256 });
}

export async function saveProgress(progress: Progress): Promise<void> {
  return invoke<void>("save_progress", { progress });
}

// ── Events ───────────────────────────────────────────────────────────

export async function onSynthesisFinished(
  handler: (payload: SynthesisFinished) => void
): Promise<() => void> {
  const listen = getTauriListen();
  if (!listen) throw new Error("Tauri event API is unavailable.");
  return listen("synthesis-finished", (event: unknown) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const e = event as any;
    handler(e.payload as SynthesisFinished);
  });
}

export async function onSynthesisProgress(
  handler: (payload: SynthesisProgress) => void
): Promise<() => void> {
  const listen = getTauriListen();
  if (!listen) throw new Error("Tauri event API is unavailable.");
  return listen("synthesis-progress", (event: unknown) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const e = event as any;
    handler(e.payload as SynthesisProgress);
  });
}

// ── LLM & AI Assistant APIs ──────────────────────────────────────────

export interface LlmConfig {
  provider: "ollama" | "llama_cpp" | "embedded_llama_cpp" | "openai" | "gemini" | "custom";
  endpoint?: string;
  model?: string;
  /** Never set by the UI: Rust adds the saved key (llmSetApiKey) to requests. */
  apiKey?: string;
  temperature?: number;
  maxTokens?: number;
  embeddingModel?: string;
  embeddingEndpoint?: string;
  modelPath?: string;
  modelDirectory?: string;
  /** llama.cpp provider: Sonara runs llama-server; Rust supplies the endpoints. */
  managedServer?: boolean;
  /** GGUF files for the managed llama-server. */
  serverModel?: string;
  serverEmbeddingModel?: string;
  contextSize?: number;
  threads?: number;
  batchSize?: number;
  idleTimeoutSeconds?: number;
}

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface LlmTestResult {
  ok: boolean;
  provider?: string;
  model?: string;
  latencyMs?: number;
  response?: string;
  error?: string;
  modelState?: string;
}

/** Code-point offsets [start, end) in a document block. */
export interface CitationSpan {
  blockId: string;
  start: number;
  end: number;
}

/** A passage an answer cites, among those the model was given. */
export interface Citation {
  /** As written in the answer, such as "Passage 3". */
  label: string;
  passageIndex: number;
  page?: number | null;
  pageLabel: PageLabel | string;
  spans: CitationSpan[];
  excerpt: string;
}

export interface LlmChatResult {
  ok: boolean;
  answer?: string;
  error?: string;
  citations?: Citation[];
}

export interface LlmSummarizeResult {
  ok: boolean;
  summary?: string;
  error?: string;
}


export const DEFAULT_LLM_CONFIG: LlmConfig = {
  provider: "ollama",
  endpoint: "http://localhost:11434/v1",
  model: "llama3.2",
  embeddingModel: "",
  temperature: 0.7,
  maxTokens: 1024,
  modelPath: "",
  modelDirectory: "",
  contextSize: 4096,
  threads: 0,
  batchSize: 512,
  idleTimeoutSeconds: 300,
};

export const LLM_STORAGE_KEY = "sonara-llm-config-v1";

// API keys never live in the webview: Settings hands a key to Rust
// (llmSetApiKey), which keeps it in the OS keychain and adds it to requests.
function withoutApiKey(config: LlmConfig): LlmConfig {
  const rest = { ...config };
  delete rest.apiKey;
  return rest;
}

export function loadStoredLlmConfig(): LlmConfig {
  try {
    const raw = localStorage.getItem(LLM_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      // Older builds could leave a key here; drop it.
      if ("apiKey" in parsed) localStorage.setItem(LLM_STORAGE_KEY, JSON.stringify(withoutApiKey(parsed)));
      return withoutApiKey({ ...DEFAULT_LLM_CONFIG, ...parsed });
    }
  } catch {
    // Fallback to default
  }
  return withoutApiKey({ ...DEFAULT_LLM_CONFIG });
}

export function saveStoredLlmConfig(config: LlmConfig): void {
  try {
    localStorage.setItem(LLM_STORAGE_KEY, JSON.stringify(withoutApiKey(config)));
  } catch {
    // Ignore storage errors
  }
}

export type LlamaServerState = "stopped" | "starting" | "ready" | "failed";

export interface LlamaServerStatus {
  state: LlamaServerState;
  endpoint?: string | null;
  embeddingEndpoint?: string | null;
  model?: string | null;
  error?: string | null;
  logTail: string[];
  restarts: number;
}

export async function llamaServerStatus(): Promise<LlamaServerStatus> {
  return invoke<LlamaServerStatus>("llama_server_status");
}

/** The llama-server program Sonara will run: the one chosen, else from PATH. */
export async function llamaServerExecutable(): Promise<string | null> {
  return invoke<string | null>("llama_server_executable");
}

export async function llamaServerChooseExecutable(): Promise<string | null> {
  return invoke<string | null>("llama_server_choose_executable");
}

export async function llamaServerStart(options: {
  model: string;
  embeddingModel?: string;
  contextSize?: number;
  threads?: number;
}): Promise<LlamaServerStatus> {
  return invoke<LlamaServerStatus>("llama_server_start", options);
}

export async function llamaServerStop(): Promise<LlamaServerStatus> {
  return invoke<LlamaServerStatus>("llama_server_stop");
}

export interface DirUsage {
  bytes: number;
  files: number;
}

export interface StorageUsage {
  audioCache: DirUsage;
  embeddingCache: DirUsage;
  sessions: DirUsage;
}

export async function storageUsage(): Promise<StorageUsage> {
  return invoke<StorageUsage>("storage_usage");
}

/** Clear a cache; returns the usage after clearing. */
export async function clearCache(kind: "audio" | "embeddings"): Promise<StorageUsage> {
  return invoke<StorageUsage>("clear_cache", { kind });
}

/** Where a saved key lives: the OS keychain, or memory for this run only. */
export type KeyStorage = "keychain" | "session";

export async function llmSetApiKey(provider: LlmConfig["provider"], key: string): Promise<KeyStorage> {
  return invoke<KeyStorage>("llm_set_api_key", { provider, key });
}

export async function llmApiKeyStatus(provider: LlmConfig["provider"]): Promise<KeyStorage | null> {
  return invoke<KeyStorage | null>("llm_api_key_status", { provider });
}

export async function llmClearApiKey(provider: LlmConfig["provider"]): Promise<void> {
  return invoke<void>("llm_clear_api_key", { provider });
}

export async function llmTestConnection(config: LlmConfig): Promise<LlmTestResult> {
  return invoke<LlmTestResult>("llm_test_connection", { config });
}

export async function llmModelStatus(config: LlmConfig): Promise<{ ok: boolean; state: string; model?: string; lastError?: string }> {
  return invoke("llm_model_status", { config });
}

export async function llmDiscoverModels(config: LlmConfig): Promise<{ ok: boolean; models: string[] }> {
  return invoke("llm_discover_models", { config });
}

export async function llmChooseModel(): Promise<string | null> {
  return invoke("llm_choose_model");
}

/** Ask about the open document; the backend gives the worker the document itself. */
export async function llmChat(
  config: LlmConfig,
  question: string,
  history?: ChatMessage[]
): Promise<LlmChatResult> {
  return invoke<LlmChatResult>("llm_chat", { config, question, history });
}

/** Summarize the open document, or `text` when given (such as a selected passage). */
export async function llmSummarize(
  config: LlmConfig,
  mode?: "summary" | "takeaways" | "explain_passage",
  text?: string
): Promise<LlmSummarizeResult> {
  return invoke<LlmSummarizeResult>("llm_summarize", { config, text, mode });
}

/** The error of a request stopped with `llmCancel`; see LLM_CANCELLED in llm_rpc.rs. */
export const LLM_CANCELLED = "The request was stopped.";

/** Stop the assistant request in flight. False when nothing was running. */
export async function llmCancel(): Promise<boolean> {
  return invoke<boolean>("llm_cancel");
}

/** The chip text for a citation: "p. 12", "sec. 3", or the passage number. */
export function citationChipLabel(citation: Citation): string {
  if (citation.page) return citation.pageLabel === "page" ? `p. ${citation.page}` : `sec. ${citation.page}`;
  return `passage ${citation.passageIndex + 1}`;
}

export async function getDocumentText(): Promise<string> {
  return invoke<string>("get_document_text");
}


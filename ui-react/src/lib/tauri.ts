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
}

export interface ReaderDocument {
  sourceSha256: string;
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
  apiKey?: string;
  temperature?: number;
  maxTokens?: number;
  embeddingModel?: string;
  embeddingEndpoint?: string;
  modelPath?: string;
  modelDirectory?: string;
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

export interface LlmChatResult {
  ok: boolean;
  answer?: string;
  error?: string;
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
  apiKey: "",
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

// The API key is never written to localStorage. It is kept only in memory for
// the lifetime of the window so Settings and the Assistant share one value.
let sessionApiKey = "";

export function loadStoredLlmConfig(): LlmConfig {
  try {
    const raw = localStorage.getItem(LLM_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      const config = { ...DEFAULT_LLM_CONFIG, ...parsed, apiKey: sessionApiKey };
      if (parsed.apiKey) localStorage.setItem(LLM_STORAGE_KEY, JSON.stringify({ ...parsed, apiKey: "" }));
      return config;
    }
  } catch {
    // Fallback to default
  }
  return { ...DEFAULT_LLM_CONFIG, apiKey: sessionApiKey };
}

export function saveStoredLlmConfig(config: LlmConfig): void {
  sessionApiKey = config.apiKey ?? "";
  try {
    localStorage.setItem(LLM_STORAGE_KEY, JSON.stringify({ ...config, apiKey: "" }));
  } catch {
    // Ignore storage errors
  }
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

export async function llmChat(
  config: LlmConfig,
  question: string,
  context?: string,
  history?: ChatMessage[]
): Promise<LlmChatResult> {
  return invoke<LlmChatResult>("llm_chat", { config, question, context, history });
}

export async function llmSummarize(
  config: LlmConfig,
  text: string,
  mode?: "summary" | "takeaways" | "explain_passage"
): Promise<LlmSummarizeResult> {
  return invoke<LlmSummarizeResult>("llm_summarize", { config, text, mode });
}

export async function getDocumentText(): Promise<string> {
  return invoke<string>("get_document_text");
}


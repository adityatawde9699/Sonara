/**
 * Type-safe bindings for Sonara's Tauri backend commands and events.
 * These types mirror the Rust structs in src-tauri/src/lib.rs.
 */

// ── Types matching Rust backend ──────────────────────────────────────

export interface SelectedDocument {
  displayName: string;
}

export interface FrontendChunk {
  durationSeconds: number;
  pauseAfterMs: number;
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

export interface Progress {
  version: number;
  sourceSha256: string;
  segment: number;
  offsetSeconds: number;
  playbackRate: number;
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

export async function currentSession(): Promise<FrontendSession | null> {
  return invoke<FrontendSession | null>("current_session");
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
  engine: SpeechEngine = "piper"
): Promise<string> {
  const args: Record<string, unknown> = { voice, variation, expandDates, expandCitations };
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
  provider: "ollama" | "llama_cpp" | "openai" | "gemini" | "custom";
  endpoint?: string;
  model?: string;
  apiKey?: string;
  temperature?: number;
  maxTokens?: number;
  embeddingModel?: string;
  embeddingEndpoint?: string;
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

export interface PronunciationOverrideSuggestion {
  source: string;
  spoken: string;
}

export interface NarrationEnhancement {
  spokenText: string;
  notes: string[];
  suggestedOverrides: PronunciationOverrideSuggestion[];
}

export interface LlmEnhanceResult {
  ok: boolean;
  enhancement?: NarrationEnhancement;
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
};

export const LLM_STORAGE_KEY = "sonara-llm-config-v1";
export const AI_NARRATION_POLISH_STORAGE_KEY = "sonara-ai-narration-polish-enabled";

export function loadStoredLlmConfig(): LlmConfig {
  try {
    const raw = localStorage.getItem(LLM_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      const config = { ...DEFAULT_LLM_CONFIG, ...parsed, apiKey: "" };
      if (parsed.apiKey) localStorage.setItem(LLM_STORAGE_KEY, JSON.stringify({ ...parsed, apiKey: "" }));
      return config;
    }
  } catch {
    // Fallback to default
  }
  return DEFAULT_LLM_CONFIG;
}

export function saveStoredLlmConfig(config: LlmConfig): void {
  try {
    localStorage.setItem(LLM_STORAGE_KEY, JSON.stringify({ ...config, apiKey: "" }));
  } catch {
    // Ignore storage errors
  }
}

export async function llmTestConnection(config: LlmConfig): Promise<LlmTestResult> {
  return invoke<LlmTestResult>("llm_test_connection", { config });
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

export async function llmEnhanceScript(
  config: LlmConfig,
  text: string
): Promise<LlmEnhanceResult> {
  return invoke<LlmEnhanceResult>("llm_enhance_script", { config, text });
}

export async function getDocumentText(path?: string): Promise<string> {
  return invoke<string>("get_document_text", { path });
}


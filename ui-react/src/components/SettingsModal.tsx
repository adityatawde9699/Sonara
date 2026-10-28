import { type FC, useState, useEffect } from "react";
import {
  type FrontendSession,
  type VoiceInfo,
  type LlmConfig,
  type LlmTestResult,
  type PiperVariation,
  type SpeechEngine,
  type ResourceProfile,
  loadStoredLlmConfig,
  saveStoredLlmConfig,
  llmTestConnection,
  llmChooseModel,
  llmDiscoverModels,
  llmModelStatus,
  AI_NARRATION_POLISH_STORAGE_KEY,
} from "../lib/tauri";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  session: FrontendSession | null;
  playbackRate: number;
  onSpeedChange: (speed: number) => void;
  voices?: VoiceInfo[];
  selectedVoice?: string;
  onVoiceChange?: (voiceId: string) => void;
  piperVariation?: PiperVariation;
  onVariationChange?: (value: PiperVariation) => void;
  speechEngine?: SpeechEngine;
  onSpeechEngineChange?: (value: SpeechEngine) => void;
  resourceProfile?: ResourceProfile;
  onResourceProfileChange?: (value: ResourceProfile) => void;
  expandDates?: boolean;
  onExpandDatesChange?: (enabled: boolean) => void;
  expandCitations?: boolean;
  onExpandCitationsChange?: (enabled: boolean) => void;
}

const SPEED_PRESETS = [
  { label: "0.8×", value: 0.8, hint: "Relaxed" },
  { label: "1.0×", value: 1.0, hint: "Normal" },
  { label: "1.2×", value: 1.2, hint: "Brisk" },
  { label: "1.5×", value: 1.5, hint: "Fast" },
];

export const SettingsModal: FC<Props> = ({
  isOpen,
  onClose,
  session,
  playbackRate,
  onSpeedChange,
  voices = [],
  selectedVoice,
  onVoiceChange,
  piperVariation = "voice_default",
  onVariationChange,
  speechEngine = "piper",
  onSpeechEngineChange,
  resourceProfile = "standard",
  onResourceProfileChange,
  expandDates = false,
  onExpandDatesChange,
  expandCitations = false,
  onExpandCitationsChange,
}) => {
  const [llmConfig, setLlmConfig] = useState<LlmConfig>(() => loadStoredLlmConfig());
  const [showApiKey, setShowApiKey] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null);
  const [modelState, setModelState] = useState("UNLOADED");
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([]);
  const [isDiscoveringModels, setIsDiscoveringModels] = useState(false);
  const [polishEnabled, setPolishEnabled] = useState<boolean>(() => {
    try {
      return localStorage.getItem(AI_NARRATION_POLISH_STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen || llmConfig.provider !== "embedded_llama_cpp") return;
    let active = true;
    llmModelStatus(llmConfig).then((status) => {
      if (active && status.ok) setModelState(status.state);
    }).catch(() => { if (active) setModelState("UNAVAILABLE"); });
    return () => { active = false; };
  }, [isOpen, llmConfig.provider]);

  if (!isOpen) return null;

  const activeVoiceId = selectedVoice || (voices.find((v) => v.isDefault)?.id ?? "en_US-ryan-medium");

  const handleProviderChange = (provider: LlmConfig["provider"]) => {
    let defaultEndpoint = "http://localhost:11434/v1";
    let defaultModel = "llama3.2";
    if (provider === "llama_cpp") {
      defaultEndpoint = "http://127.0.0.1:9931/v1";
      defaultModel = "local-model";
    } else if (provider === "embedded_llama_cpp") {
      defaultEndpoint = "";
      defaultModel = "GGUF model";
    } else if (provider === "openai") {
      defaultEndpoint = "https://api.openai.com/v1";
      defaultModel = "gpt-4o-mini";
    } else if (provider === "gemini") {
      defaultEndpoint = "https://generativelanguage.googleapis.com/v1beta/openai";
      defaultModel = "gemini-1.5-flash";
    }
    const updated: LlmConfig = {
      ...llmConfig,
      provider,
      endpoint: defaultEndpoint,
      model: defaultModel,
    };
    setLlmConfig(updated);
    saveStoredLlmConfig(updated);
    setTestResult(null);
    if (provider === "embedded_llama_cpp") setModelState("UNLOADED");
  };

  const handleConfigUpdate = (patch: Partial<LlmConfig>) => {
    const updated: LlmConfig = { ...llmConfig, ...patch };
    setLlmConfig(updated);
    saveStoredLlmConfig(updated);
    setTestResult(null);
  };

  const handlePolishToggle = (enabled: boolean) => {
    setPolishEnabled(enabled);
    try {
      localStorage.setItem(AI_NARRATION_POLISH_STORAGE_KEY, String(enabled));
    } catch {
      // storage unavailable
    }
  };

  const handleTestConnection = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      if (llmConfig.provider === "embedded_llama_cpp") setModelState("LOADING");
      const result = await llmTestConnection(llmConfig);
      setTestResult(result);
      if (llmConfig.provider === "embedded_llama_cpp") {
        const error = result.error?.toLowerCase() || "";
        setModelState(result.ok ? (result.modelState || "IDLE") : !llmConfig.modelPath ? "NOT_CONFIGURED" : error.includes("runtime is unavailable") ? "RUNTIME_UNAVAILABLE" : error.includes("not found") || error.includes("not readable") ? "MODEL_MISSING" : "FAILED");
      }
    } catch (err: unknown) {
      setTestResult({
        ok: false,
        error: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleChooseModel = async () => {
    try {
      const path = await llmChooseModel();
      if (path) handleConfigUpdate({ modelPath: path });
    } catch (error) {
      setTestResult({ ok: false, error: error instanceof Error ? error.message : String(error) });
    }
  };

  const handleDiscoverModels = async () => {
    setIsDiscoveringModels(true);
    try {
      const result = await llmDiscoverModels(llmConfig);
      setDiscoveredModels(result.models || []);
      if (!result.models?.length) setTestResult({ ok: false, error: "No GGUF files found in the configured directory or Sonara model folders." });
    } catch (error) {
      setTestResult({ ok: false, error: error instanceof Error ? error.message : String(error) });
    } finally {
      setIsDiscoveringModels(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div className="modal-title-wrap">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
            <h2 id="settings-title">Audio & Engine Settings</h2>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Close settings dialog"
          >
            ✕
          </button>
        </div>

        {/* Dynamic Voice Selection */}
        <div className="settings-section">
          <h3 className="settings-section-title">Speech engine</h3>
          <label className="llm-field">
            <span className="llm-label">Local narration engine</span>
            <select className="voice-select" aria-label="Speech engine" value={speechEngine} onChange={(event) => onSpeechEngineChange?.(event.target.value as SpeechEngine)}>
              <option value="piper">Piper · installed voice models</option>
              <option value="kokoro">Kokoro · requires local model files and kokoro-onnx</option>
            </select>
          </label>
          {speechEngine === "kokoro" && <p className="settings-section-desc">Kokoro runs on this device when configured. Sonara expects kokoro-v1.0.onnx and voices-v1.0.bin in models/kokoro, plus kokoro-onnx in its Python environment. Model downloads are not automatic.</p>}
        </div>

        <div className="settings-section">
          <div className="settings-section-head">
            <h3 className="settings-section-title">Narration Voice</h3>
            {speechEngine === "piper" && voices.length > 0 && (
              <span className="settings-badge" data-testid="voice-count-badge">
                {voices.length} {voices.length === 1 ? "voice" : "voices"} installed
              </span>
            )}
          </div>
          <p className="settings-section-desc">
            {speechEngine === "kokoro" ? "Choose a Kokoro voice preset." : "Choose an installed Piper voice for your documents."}
          </p>
          <div className="voice-select-field">
            <label htmlFor="voice-select" className="visually-hidden">
              Select narration voice
            </label>
            <select
              id="voice-select"
              className="voice-select"
              value={activeVoiceId}
              onChange={(e) => onVoiceChange?.(e.target.value)}
              aria-label="Select narration voice"
            >
              {speechEngine === "kokoro" ? (
                <>
                  <option value="af_sarah">Sarah · US English</option>
                  <option value="af_heart">Heart · US English</option>
                  <option value="am_adam">Adam · US English</option>
                  <option value="am_michael">Michael · US English</option>
                </>
              ) : voices.length > 0 ? (
                voices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))
              ) : (
                <option value="en_US-ryan-medium">Ryan (American Male · Natural)</option>
              )}
            </select>
          </div>
        </div>

        {speechEngine === "piper" && <div className="settings-section">
          <h3 className="settings-section-title">Voice variation</h3>
          <p className="settings-section-desc">
            Adjust Piper’s generation variation. This does not control pitch or emotion; the voice default is the reference setting.
          </p>
          <label className="llm-field">
            <span className="llm-label">Variation profile</span>
            <select
              className="voice-select"
              aria-label="Piper variation profile"
              value={piperVariation}
              onChange={(event) => onVariationChange?.(event.target.value as PiperVariation)}
            >
              <option value="voice_default">Voice default</option>
              <option value="less">Less variation</option>
              <option value="more">More variation</option>
            </select>
          </label>
        </div>}

        <div className="settings-section">
          <h3 className="settings-section-title">Spoken text adjustments</h3>
          <p className="settings-section-desc">
            Sonara keeps your document unchanged. These optional rules affect narration only and can be reviewed before you prepare audio.
          </p>
          <label className="llm-toggle-label">
            <input
              type="checkbox"
              className="llm-checkbox"
              checked={expandDates}
              onChange={(event) => onExpandDatesChange?.(event.target.checked)}
            />
            <span className="llm-toggle-text"><strong>Expand ISO dates</strong><span className="llm-toggle-sub">For example, 2026-10-27 becomes “October twenty-seventh, twenty twenty-six.”</span></span>
          </label>
          <label className="llm-toggle-label">
            <input
              type="checkbox"
              className="llm-checkbox"
              checked={expandCitations}
              onChange={(event) => onExpandCitationsChange?.(event.target.checked)}
            />
            <span className="llm-toggle-text"><strong>Read bracketed numeric citations</strong><span className="llm-toggle-sub">For example, [12, 14] becomes “references twelve and fourteen.”</span></span>
          </label>
        </div>

        <div className="settings-section">
          <h3 className="settings-section-title">Resource profile</h3>
          <p className="settings-section-desc">Controls Sonara's TTS prefetch and audio cache limits. It does not change your selected model or configure an external llama.cpp server.</p>
          <div className="llm-field">
            <label htmlFor="resource-profile" className="llm-label">Inference and cache policy</label>
            <select id="resource-profile" className="llm-input" value={resourceProfile} onChange={(event) => onResourceProfileChange?.(event.target.value as ResourceProfile)}>
              <option value="low_resource">Low resource · one pending audio chunk, 128 MiB cache</option>
              <option value="standard">Standard · Piper defaults, 512 MiB cache</option>
              <option value="high_performance">High performance · larger prefetch, 1 GiB cache</option>
            </select>
          </div>
        </div>

        {/* AI Assistant & Smart Narration */}
        <div className="settings-section">
          <div className="settings-section-head">
            <h3 className="settings-section-title">AI Assistant & Smart Narration</h3>
            <span className="settings-badge" data-testid="llm-provider-badge">
              {llmConfig.provider === "embedded_llama_cpp" ? "Local · embedded" : llmConfig.provider === "ollama" || llmConfig.provider === "llama_cpp" ? "Local · loopback" : "Cloud API"}
            </span>
          </div>
          <p className="settings-section-desc">
            Embedded llama.cpp loads a selected GGUF directly in Sonara and unloads it after inactivity. Ollama and the legacy llama.cpp server remain separate HTTP providers. Cloud providers receive document context included with your request.
          </p>

          <div className="llm-form-grid">
            {/* Provider */}
            <div className="llm-field">
              <label htmlFor="llm-provider" className="llm-label">
                Provider
              </label>
              <select
                id="llm-provider"
                className="voice-select"
                value={llmConfig.provider}
                onChange={(e) => handleProviderChange(e.target.value as LlmConfig["provider"])}
              >
                <option value="ollama">Ollama (Local & Private · Recommended)</option>
                <option value="embedded_llama_cpp">llama.cpp embedded (Local · GGUF, no server)</option>
                <option value="llama_cpp">llama.cpp server (Legacy HTTP · GGUF)</option>
                <option value="gemini">Google Gemini (Gemini 1.5 Flash)</option>
                <option value="openai">OpenAI (GPT-4o mini)</option>
                <option value="custom">Custom (OpenAI-Compatible / LM Studio)</option>
              </select>
            </div>

            {llmConfig.provider === "embedded_llama_cpp" ? <>
              <div className="llm-field">
                <label htmlFor="llm-model-path" className="llm-label">GGUF model file</label>
                <div className="llm-test-bar">
                  <input id="llm-model-path" type="text" className="llm-input" value={llmConfig.modelPath || ""} onChange={(e) => handleConfigUpdate({ modelPath: e.target.value })} placeholder="Select a readable .gguf file" />
                  <button type="button" className="button button-secondary" onClick={handleChooseModel}>Browse…</button>
                </div>
                <span className="llm-hint">Model weights are not downloaded automatically. Compatible chat templates are read from GGUF metadata when available.</span>
                <span className="llm-hint">Embedded document chat currently uses a bounded text excerpt; it does not run vector embeddings or send requests to a server.</span>
              </div>
              <div className="llm-field">
                <label htmlFor="llm-model-directory" className="llm-label">Additional model directory</label>
                <input id="llm-model-directory" type="text" className="llm-input" value={llmConfig.modelDirectory || ""} onChange={(e) => handleConfigUpdate({ modelDirectory: e.target.value })} placeholder="Optional directory to search" />
                <div className="llm-test-bar"><button type="button" className="button button-secondary" onClick={handleDiscoverModels} disabled={isDiscoveringModels}>{isDiscoveringModels ? "Searching…" : "Find GGUF models"}</button></div>
                {discoveredModels.length > 0 && <select className="voice-select" aria-label="Discovered GGUF models" value={llmConfig.modelPath || ""} onChange={(e) => handleConfigUpdate({ modelPath: e.target.value })}><option value="">Choose a discovered model</option>{discoveredModels.map((path) => <option key={path} value={path}>{path}</option>)}</select>}
              </div>
              <div className="llm-form-grid">
                <label className="llm-field"><span className="llm-label">Context size</span><input type="number" className="llm-input" min={512} max={131072} step={512} value={llmConfig.contextSize ?? 4096} onChange={(e) => handleConfigUpdate({ contextSize: Number(e.target.value) })} /></label>
                <label className="llm-field"><span className="llm-label">CPU threads · 0 = automatic</span><input type="number" className="llm-input" min={0} max={256} value={llmConfig.threads ?? 0} onChange={(e) => handleConfigUpdate({ threads: Number(e.target.value) })} /></label>
                <label className="llm-field"><span className="llm-label">Batch size</span><input type="number" className="llm-input" min={32} max={8192} step={32} value={llmConfig.batchSize ?? 512} onChange={(e) => handleConfigUpdate({ batchSize: Number(e.target.value) })} /></label>
                <div className="llm-field"><label htmlFor="llm-idle-timeout" className="llm-label">Idle unload · seconds</label><input id="llm-idle-timeout" type="number" className="llm-input" min={0} max={86400} step={30} value={llmConfig.idleTimeoutSeconds ?? 300} onChange={(e) => handleConfigUpdate({ idleTimeoutSeconds: Number(e.target.value) })} /><span className="llm-hint">0 keeps the model loaded until Sonara closes.</span></div>
              </div>
              <div className="llm-test-result" role="status" data-testid="embedded-model-state">Model state: {{ NOT_CONFIGURED: "model not configured", MODEL_MISSING: "model file missing", RUNTIME_UNAVAILABLE: "runtime unavailable", UNLOADED: "not loaded", LOADING: "loading model", READY: "ready", IN_USE: "generating response", IDLE: "ready · idle", UNLOADING: "unloading model", FAILED: "inference failed", UNAVAILABLE: "runtime unavailable" }[modelState] || modelState.toLowerCase()}</div>
              <div className="llm-form-grid">
                <label className="llm-field"><span className="llm-label">Temperature</span><input type="number" className="llm-input" min={0} max={2} step={0.1} value={llmConfig.temperature ?? 0.7} onChange={(e) => handleConfigUpdate({ temperature: Number(e.target.value) })} /></label>
                <label className="llm-field"><span className="llm-label">Maximum response tokens</span><input type="number" className="llm-input" min={1} max={32768} step={128} value={llmConfig.maxTokens ?? 1024} onChange={(e) => handleConfigUpdate({ maxTokens: Number(e.target.value) })} /></label>
              </div>
            </> : <>
            {/* Endpoint */}
            <div className="llm-field">
              <label htmlFor="llm-endpoint" className="llm-label">
                API Endpoint URL
              </label>
              <input
                id="llm-endpoint"
                type="text"
                className="llm-input"
                value={llmConfig.endpoint || ""}
                onChange={(e) => handleConfigUpdate({ endpoint: e.target.value })}
                placeholder={llmConfig.provider === "llama_cpp" ? "http://127.0.0.1:9931/v1" : "http://localhost:11434/v1"}
              />
            </div>

            {/* Model Name */}
            <div className="llm-field">
              <label htmlFor="llm-model" className="llm-label">
                Model Name
              </label>
              <input
                id="llm-model"
                type="text"
                className="llm-input"
                value={llmConfig.model || ""}
                onChange={(e) => handleConfigUpdate({ model: e.target.value })}
                placeholder="llama3.2"
              />
            </div>

            {llmConfig.provider === "llama_cpp" && <div className="llm-field">
              <label htmlFor="llm-embedding-endpoint" className="llm-label">Embedding server URL</label>
              <input id="llm-embedding-endpoint" type="text" className="llm-input" value={llmConfig.embeddingEndpoint || ""} onChange={(event) => handleConfigUpdate({ embeddingEndpoint: event.target.value })} placeholder="same server as chat" />
              <span className="llm-hint">Optional separate loopback server running an embedding model with --embedding.</span>
            </div>}
            </>}

            {llmConfig.provider === "llama_cpp" && <div className="llm-field">
              <label htmlFor="llm-embedding-model" className="llm-label">Embedding model alias</label>
              <input id="llm-embedding-model" type="text" className="llm-input" value={llmConfig.embeddingModel || ""} onChange={(event) => handleConfigUpdate({ embeddingModel: event.target.value })} placeholder="same as server model" />
              <span className="llm-hint">Requires a llama.cpp server started with --embedding. Leave blank if the server uses one model for chat and embeddings.</span>
            </div>}

            {/* API Key */}
            {llmConfig.provider !== "embedded_llama_cpp" && <>
            <div className="llm-field">
              <div className="llm-field-head">
                <label htmlFor="llm-api-key" className="llm-label">
                  API Key
                </label>
                {llmConfig.provider === "ollama" || llmConfig.provider === "llama_cpp" ? (
                  <span className="llm-hint">Not required for local inference</span>
                ) : (
                  <button
                    type="button"
                    className="llm-toggle-key-btn"
                    onClick={() => setShowApiKey(!showApiKey)}
                  >
                    {showApiKey ? "Hide" : "Show"}
                  </button>
                )}
              </div>
              <input
                id="llm-api-key"
                type={showApiKey ? "text" : "password"}
                className="llm-input"
                value={llmConfig.apiKey || ""}
                onChange={(e) => handleConfigUpdate({ apiKey: e.target.value })}
                placeholder={llmConfig.provider === "ollama" || llmConfig.provider === "llama_cpp" ? "Optional for local inference" : "sk-..."}
              />
            </div>
            </>}
          </div>

          {/* Test Connection Button & Status */}
          <div className="llm-test-bar">
            <button
              type="button"
              className="button button-secondary"
              onClick={handleTestConnection}
              disabled={isTesting}
            >
              {isTesting ? "Testing Connection…" : "Test Connection"}
            </button>
            {testResult && (
              <div
                className={`llm-test-result ${testResult.ok ? "success" : "failure"}`}
                role="status"
              >
                {testResult.ok ? (
                  <span>
                    ✓ Connected ({testResult.model}, {testResult.latencyMs}ms)
                  </span>
                ) : (
                  <span title={testResult.error}>
                    ✕ Connection failed: {testResult.error}
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Smart Narration Polish Toggle */}
          <div className="llm-toggle-row">
            <label className="llm-checkbox-label" htmlFor="enable-polish">
              <input
                id="enable-polish"
                type="checkbox"
                className="llm-checkbox"
                checked={polishEnabled}
                onChange={(e) => handlePolishToggle(e.target.checked)}
              />
              <span className="llm-toggle-text">
                <strong>Enable AI Narration Polish</strong>
                <span className="llm-toggle-sub">
                  Cleans extraction artifacts and broken line wraps, and suggests pronunciations before reading.
                </span>
              </span>
            </label>
          </div>
        </div>

        {/* Speed Presets */}
        <div className="settings-section">
          <h3 className="settings-section-title">Speed Presets</h3>
          <div className="speed-presets-grid">
            {SPEED_PRESETS.map((preset) => {
              const active = Math.abs(playbackRate - preset.value) < 0.05;
              return (
                <button
                  key={preset.value}
                  type="button"
                  className={`preset-btn ${active ? "active" : ""}`}
                  onClick={() => onSpeedChange(preset.value)}
                >
                  <span className="preset-val">{preset.label}</span>
                  <span className="preset-hint">{preset.hint}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Specs & Privacy */}
        <div className="settings-section">
          <h3 className="settings-section-title">Speech Engine & Privacy</h3>
          <div className="specs-list">
            <div className="spec-row">
              <span className="spec-label">Active Document Voice</span>
              <span className="spec-value">{session?.voice ?? activeVoiceId}</span>
            </div>
            <div className="spec-row">
              <span className="spec-label">Engine Runtime</span>
              <span className="spec-value">{session?.engine ?? (speechEngine === "kokoro" ? "Kokoro · optional local runtime" : "Piper · ONNX Runtime CPU")}</span>
            </div>
            <div className="spec-row">
              <span className="spec-label">Audio Quality</span>
              <span className="spec-value">
                {session ? `${session.sampleRate} Hz · ${session.channels === 1 ? "Mono" : "Stereo"} · 16-bit PCM` : "22,050 Hz · Mono · 16-bit PCM"}
              </span>
            </div>
            <div className="spec-row">
              <span className="spec-label">Narration Ruleset</span>
              <span className="spec-value">v{session?.narrationRulesetVersion ?? "1"} (Deterministic pauses & spans)</span>
            </div>
            <div className="spec-row">
              <span className="spec-label">Privacy Guarantee</span>
              <span className="spec-value highlight-green">Narration stays local. Assistant provider is configured separately.</span>
            </div>
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" className="button button-primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
};

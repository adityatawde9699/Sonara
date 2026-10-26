import { type FC, useState, useEffect } from "react";
import {
  type FrontendSession,
  type VoiceInfo,
  type LlmConfig,
  type LlmTestResult,
  type PiperVariation,
  loadStoredLlmConfig,
  saveStoredLlmConfig,
  llmTestConnection,
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
  expandDates = false,
  onExpandDatesChange,
  expandCitations = false,
  onExpandCitationsChange,
}) => {
  const [llmConfig, setLlmConfig] = useState<LlmConfig>(() => loadStoredLlmConfig());
  const [showApiKey, setShowApiKey] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null);
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

  if (!isOpen) return null;

  const activeVoiceId = selectedVoice || (voices.find((v) => v.isDefault)?.id ?? "en_US-ryan-medium");

  const handleProviderChange = (provider: LlmConfig["provider"]) => {
    let defaultEndpoint = "http://localhost:11434/v1";
    let defaultModel = "llama3.2";
    if (provider === "openai") {
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
      const result = await llmTestConnection(llmConfig);
      setTestResult(result);
    } catch (err: unknown) {
      setTestResult({
        ok: false,
        error: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setIsTesting(false);
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
          <div className="settings-section-head">
            <h3 className="settings-section-title">Narration Voice</h3>
            {voices.length > 0 && (
              <span className="settings-badge" data-testid="voice-count-badge">
                {voices.length} {voices.length === 1 ? "voice" : "voices"} installed
              </span>
            )}
          </div>
          <p className="settings-section-desc">
            Choose the neural Piper voice that reads your documents. Natural models provide warm cadence and fluid phrasing.
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
              {voices.length > 0 ? (
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

        <div className="settings-section">
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
        </div>

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

        {/* AI Assistant & Smart Narration */}
        <div className="settings-section">
          <div className="settings-section-head">
            <h3 className="settings-section-title">AI Assistant & Smart Narration</h3>
            <span className="settings-badge" data-testid="llm-provider-badge">
              {llmConfig.provider === "ollama" ? "Local Offline" : "Cloud API"}
            </span>
          </div>
          <p className="settings-section-desc">
            Connect a local or cloud LLM for document Q&A, comprehensive summaries, and smart narration cleanup.
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
                <option value="gemini">Google Gemini (Gemini 1.5 Flash)</option>
                <option value="openai">OpenAI (GPT-4o mini)</option>
                <option value="custom">Custom (OpenAI-Compatible / LM Studio)</option>
              </select>
            </div>

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
                placeholder="http://localhost:11434/v1"
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

            {/* API Key */}
            <div className="llm-field">
              <div className="llm-field-head">
                <label htmlFor="llm-api-key" className="llm-label">
                  API Key
                </label>
                {llmConfig.provider === "ollama" ? (
                  <span className="llm-hint">Not required for local Ollama</span>
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
                placeholder={llmConfig.provider === "ollama" ? "Optional for local Ollama" : "sk-..."}
              />
            </div>
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
              <span className="spec-value">Piper 1.8.0 (ONNX Runtime CPU)</span>
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
              <span className="spec-value highlight-green">100% Offline (Local loopback with bearer auth)</span>
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

import { useCallback, useEffect, useState } from "react";
import {
  type LlamaServerStatus,
  type LlmConfig,
  llamaServerChooseExecutable,
  llamaServerExecutable,
  llamaServerStart,
  llamaServerStatus,
  llamaServerStop,
  llmChooseModel,
} from "../lib/tauri";

interface Props {
  config: LlmConfig;
  onChange: (patch: Partial<LlmConfig>) => void;
}

const STATE_TEXT: Record<LlamaServerStatus["state"], string> = {
  stopped: "Stopped",
  starting: "Loading the model…",
  ready: "Ready",
  failed: "Failed",
};

/** Start, watch and stop the llama-server Sonara runs for the assistant. */
export function LlamaServerPanel({ config, onChange }: Props) {
  const [program, setProgram] = useState<string | null | undefined>(undefined);
  const [status, setStatus] = useState<LlamaServerStatus | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setStatus(await llamaServerStatus());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  useEffect(() => {
    let active = true;
    llamaServerExecutable().then((path) => { if (active) setProgram(path); }).catch(() => { if (active) setProgram(null); });
    llamaServerStatus().then((next) => { if (active) setStatus(next); }).catch(() => {});
    return () => { active = false; };
  }, []);

  // Poll while the model loads.
  useEffect(() => {
    if (status?.state !== "starting") return;
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => window.clearInterval(timer);
  }, [refresh, status?.state]);

  const run = async (action: () => Promise<LlamaServerStatus>) => {
    setError("");
    try {
      setStatus(await action());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const choose = async (field: "serverModel" | "serverEmbeddingModel") => {
    try {
      const path = await llmChooseModel();
      if (path) onChange({ [field]: path });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const running = status?.state === "starting" || status?.state === "ready";
  return (
    <div className="llama-server-panel">
      <div className="llm-field">
        <span className="llm-label">Program</span>
        <div className="llm-test-bar">
          <span className="llama-server-path mono" title={program ?? undefined}>
            {program === undefined ? "…" : program ?? "llama-server was not found on PATH"}
          </span>
          <button
            type="button"
            className="button button-secondary"
            onClick={async () => {
              try {
                const picked = await llamaServerChooseExecutable();
                if (picked) setProgram(picked);
              } catch (cause) {
                setError(cause instanceof Error ? cause.message : String(cause));
              }
            }}
          >Choose…</button>
        </div>
      </div>
      <div className="llm-field">
        <label htmlFor="llama-server-model" className="llm-label">Chat model (GGUF)</label>
        <div className="llm-test-bar">
          <input id="llama-server-model" type="text" className="llm-input" value={config.serverModel || ""} onChange={(e) => onChange({ serverModel: e.target.value })} placeholder="Select a .gguf file" />
          <button type="button" className="button button-secondary" onClick={() => void choose("serverModel")}>Browse…</button>
        </div>
      </div>
      <div className="llm-field">
        <label htmlFor="llama-server-embedding-model" className="llm-label">Embedding model (GGUF, optional)</label>
        <div className="llm-test-bar">
          <input id="llama-server-embedding-model" type="text" className="llm-input" value={config.serverEmbeddingModel || ""} onChange={(e) => onChange({ serverEmbeddingModel: e.target.value })} placeholder="Keyword search only without one" />
          <button type="button" className="button button-secondary" onClick={() => void choose("serverEmbeddingModel")}>Browse…</button>
        </div>
        <span className="llm-hint">A second server runs this model with --embeddings, so questions also match by meaning.</span>
      </div>
      <div className="llm-test-bar">
        {running ? (
          <button type="button" className="button button-secondary" onClick={() => void run(llamaServerStop)}>Stop server</button>
        ) : (
          <button
            type="button"
            className="button button-secondary"
            disabled={!program || !config.serverModel?.trim()}
            onClick={() => void run(() => llamaServerStart({
              model: config.serverModel!.trim(),
              embeddingModel: config.serverEmbeddingModel?.trim() || undefined,
              contextSize: config.contextSize,
              threads: config.threads || undefined,
            }))}
          >Start server</button>
        )}
        <span className={`llm-test-result ${status?.state === "ready" ? "success" : status?.state === "failed" ? "failure" : ""}`} role="status">
          {status ? STATE_TEXT[status.state] : "…"}
          {status?.state === "ready" && status.endpoint && <> · <span className="mono">{status.endpoint}</span></>}
          {status?.state === "failed" && status.error && <> · {status.error}</>}
        </span>
      </div>
      {status?.state === "failed" && status.logTail.length > 0 && (
        <details className="llama-server-log">
          <summary>Server output</summary>
          <pre>{status.logTail.join("\n")}</pre>
        </details>
      )}
      {error && <span className="llm-hint api-key-error" role="alert">{error}</span>}
    </div>
  );
}

import { useEffect, useState } from "react";
import { type KeyStorage, type LlmConfig, llmApiKeyStatus, llmClearApiKey, llmSetApiKey } from "../lib/tauri";

interface Props {
  provider: LlmConfig["provider"];
  /** Local servers usually need no key. */
  optional?: boolean;
}

/**
 * Saves the provider's API key through Rust into the OS keychain. The key
 * is never read back into the webview: once saved, only where it is kept
 * is shown.
 */
export function ApiKeyField({ provider, optional = false }: Props) {
  const [stored, setStored] = useState<KeyStorage | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    llmApiKeyStatus(provider)
      .then((status) => {
        if (!active) return;
        setStored(status);
        setEditing(false);
        setDraft("");
        setError("");
      })
      .catch(() => { if (active) setStored(null); });
    return () => { active = false; };
  }, [provider]);

  const save = async () => {
    if (!draft.trim()) return;
    setBusy(true);
    setError("");
    try {
      setStored(await llmSetApiKey(provider, draft));
      setDraft("");
      setEditing(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      await llmClearApiKey(provider);
      setStored(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const showInput = !stored || editing;
  return (
    <div className="llm-field">
      <div className="llm-field-head">
        <label htmlFor="llm-api-key" className="llm-label">API Key</label>
        {optional ? (
          <span className="llm-hint">Not required for local inference</span>
        ) : showInput && (
          <button type="button" className="llm-toggle-key-btn" onClick={() => setShow(!show)}>
            {show ? "Hide" : "Show"}
          </button>
        )}
      </div>
      {showInput ? (
        <form
          className="api-key-row"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <input
            id="llm-api-key"
            type={show ? "text" : "password"}
            className="llm-input"
            value={draft}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={optional ? "Optional for local inference" : "sk-..."}
          />
          <button type="submit" className="button button-secondary" disabled={busy || !draft.trim()}>Save key</button>
          {editing && <button type="button" className="text-button" onClick={() => { setEditing(false); setDraft(""); }}>Cancel</button>}
        </form>
      ) : (
        <div className="api-key-row" role="status">
          <span className="api-key-status">
            {stored === "keychain" ? "Saved in your system keychain" : "Key kept for this session only (no system keychain is available)"}
          </span>
          <button type="button" className="text-button" onClick={() => setEditing(true)} disabled={busy}>Replace</button>
          <button type="button" className="text-button" onClick={() => void remove()} disabled={busy}>Remove</button>
        </div>
      )}
      {error && <span className="llm-hint api-key-error" role="alert">{error}</span>}
    </div>
  );
}

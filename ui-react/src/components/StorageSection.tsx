import { useEffect, useState } from "react";
import { formatBytes } from "../lib/format";
import { type DirUsage, type StorageUsage, clearCache, storageUsage } from "../lib/tauri";

const describe = (usage: DirUsage) =>
  usage.files
    ? `${formatBytes(usage.bytes)} · ${usage.files.toLocaleString()} ${usage.files === 1 ? "file" : "files"}`
    : "Empty";

interface Row {
  key: "audio" | "embeddings" | null;
  label: string;
  hint: string;
  usage: (all: StorageUsage) => DirUsage;
}

const ROWS: Row[] = [
  {
    key: "audio",
    label: "Audio cache",
    hint: "Synthesized passages, reused when a document is prepared again.",
    usage: (all) => all.audioCache,
  },
  {
    key: "embeddings",
    label: "Assistant embeddings",
    hint: "Search vectors from a local embedding server; rebuilt on the next question.",
    usage: (all) => all.embeddingCache,
  },
  {
    key: null,
    label: "Current session",
    hint: "The document you are listening to. Replaced when you prepare another.",
    usage: (all) => all.sessions,
  },
];

/** Sizes of Sonara's local data, with controls to clear the caches. */
export function StorageSection() {
  const [usage, setUsage] = useState<StorageUsage | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    storageUsage()
      .then((next) => { if (active) setUsage(next); })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : String(cause)); });
    return () => { active = false; };
  }, []);

  const clear = async (kind: "audio" | "embeddings") => {
    setBusy(kind);
    setError("");
    try {
      setUsage(await clearCache(kind));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="settings-section">
      <h3 className="settings-section-title">Storage</h3>
      <p className="settings-section-desc">Everything here stays on this device. Clearing a cache does not affect the session you have open.</p>
      <dl className="storage-list">
        {ROWS.map((row) => (
          <div className="storage-row" key={row.label}>
            <dt>
              <span className="storage-label">{row.label}</span>
              <span className="llm-hint">{row.hint}</span>
            </dt>
            <dd>
              <span className="storage-size mono">{usage ? describe(row.usage(usage)) : "…"}</span>
              {row.key && (
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={!usage || busy !== null || row.usage(usage).files === 0}
                  onClick={() => void clear(row.key!)}
                  aria-label={`Clear ${row.label.toLowerCase()}`}
                >
                  {busy === row.key ? "Clearing…" : "Clear"}
                </button>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {error && <p className="llm-hint api-key-error" role="alert">{error}</p>}
    </div>
  );
}

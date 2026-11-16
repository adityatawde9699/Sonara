import { type FC, useCallback, useEffect, useRef, useState } from "react";
import {
  cancelModelDownload,
  installModel,
  listModels,
  onModelDownloadProgress,
  type ModelDownloadProgress,
  type ModelStatus,
} from "../lib/tauri";

interface Props {
  /** Called after a model is installed, so voice lists can be reloaded. */
  onInstalled?: () => void;
}

function formatSize(bytes: number): string {
  const megabytes = bytes / (1024 * 1024);
  return megabytes >= 100 ? `${Math.round(megabytes)} MB` : `${megabytes.toFixed(1)} MB`;
}

/**
 * Lists the speech models Sonara can download and installs them on request.
 * Installers ship without models; each download is checked against a pinned
 * SHA-256 hash by the backend before it is used.
 */
export const ModelDownloads: FC<Props> = ({ onInstalled }) => {
  const [models, setModels] = useState<ModelStatus[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [downloading, setDownloading] = useState<string | null>(null);
  const [progress, setProgress] = useState<ModelDownloadProgress | null>(null);
  const [message, setMessage] = useState<{ model: string; text: string; ok: boolean } | null>(null);
  const mounted = useRef(true);

  const refresh = useCallback(
    () =>
      listModels().then(
        (rows) => {
          if (mounted.current) {
            setModels(rows);
            setLoadError("");
          }
        },
        (error: unknown) => {
          if (mounted.current) setLoadError(error instanceof Error ? error.message : String(error));
        },
      ),
    [],
  );

  useEffect(() => {
    mounted.current = true;
    void refresh();
    let unlisten: (() => void) | undefined;
    void onModelDownloadProgress((payload) => {
      if (mounted.current) setProgress(payload);
    })
      .then((stop) => {
        if (mounted.current) unlisten = stop;
        else stop();
      })
      .catch(() => {
        /* progress events unavailable: the download still completes */
      });
    return () => {
      mounted.current = false;
      unlisten?.();
    };
  }, [refresh]);

  const download = async (model: ModelStatus) => {
    setDownloading(model.id);
    setProgress({ model: model.id, received: 0, total: model.sizeBytes });
    setMessage(null);
    try {
      await installModel(model.id);
      if (!mounted.current) return;
      setMessage({ model: model.id, text: `${model.label} is installed.`, ok: true });
      await refresh();
      onInstalled?.();
    } catch (error) {
      if (!mounted.current) return;
      setMessage({ model: model.id, text: error instanceof Error ? error.message : String(error), ok: false });
    } finally {
      if (mounted.current) {
        setDownloading(null);
        setProgress(null);
      }
    }
  };

  const cancel = () => {
    void cancelModelDownload();
  };

  const rows = models ?? [];
  const kokoro = rows.filter((model) => model.kind === "kokoro");
  const piper = rows.filter((model) => model.kind === "piper");

  const renderRow = (model: ModelStatus) => {
    const active = downloading === model.id;
    const percent =
      active && progress && progress.model === model.id && progress.total > 0
        ? Math.min(100, Math.floor((progress.received / progress.total) * 100))
        : 0;
    return (
      <li key={model.id} className="model-row">
        <div className="model-row-text">
          <span className="model-row-name">{model.label}</span>
          <span className="model-row-meta">{formatSize(model.sizeBytes)}</span>
        </div>
        {model.installed ? (
          <span className="settings-badge">Installed</span>
        ) : active ? (
          <div className="model-row-progress">
            <progress
              max={100}
              value={percent}
              aria-label={`Downloading ${model.label}`}
            />
            <span className="model-row-meta" aria-live="polite">{percent}%</span>
            <button type="button" className="button button-secondary" onClick={cancel}>
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void download(model)}
            disabled={downloading !== null}
            aria-label={`Download ${model.label}, ${formatSize(model.sizeBytes)}`}
          >
            Download
          </button>
        )}
      </li>
    );
  };

  return (
    <div className="settings-section" data-testid="model-downloads">
      <h3 className="settings-section-title">Speech models</h3>
      <p className="settings-section-desc">
        Installers do not include voice models. Download the ones you want to use: Piper voices come from Hugging Face
        and Kokoro from its GitHub release. Each file is checked against a pinned SHA-256 hash before Sonara uses it.
      </p>
      {loadError && (
        <p className="llm-test-result failure" role="alert">
          {loadError}
        </p>
      )}
      {models === null && !loadError && <p className="llm-hint">Checking installed models…</p>}
      {piper.length > 0 && (
        <>
          <h4 className="model-group-title">Piper voices</h4>
          <ul className="model-list">{piper.map(renderRow)}</ul>
        </>
      )}
      {kokoro.length > 0 && (
        <>
          <h4 className="model-group-title">Kokoro</h4>
          <ul className="model-list">{kokoro.map(renderRow)}</ul>
        </>
      )}
      {message && (
        <p className={`llm-test-result ${message.ok ? "success" : "failure"}`} role={message.ok ? "status" : "alert"}>
          {message.text}
        </p>
      )}
    </div>
  );
};

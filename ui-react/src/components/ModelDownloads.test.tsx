import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ModelDownloads } from "./ModelDownloads";
import type { ModelDownloadProgress, ModelStatus } from "../lib/tauri";

const MODELS: ModelStatus[] = [
  { id: "en_US-ryan-medium", kind: "piper", label: "Ryan (American English, male)", sizeBytes: 63_206_177, installed: true },
  { id: "en_US-lessac-medium", kind: "piper", label: "Lessac (American English, female)", sizeBytes: 63_206_179, installed: false },
  { id: "kokoro", kind: "kokoro", label: "Kokoro v1.0 (multilingual)", sizeBytes: 353_719_767, installed: false },
];

type Invoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;

let progressHandler: ((event: { payload: ModelDownloadProgress }) => void) | null = null;

function installTauri(invoke: Invoke) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).__TAURI__ = {
    core: { invoke },
    event: {
      listen: async (_event: string, handler: (event: { payload: ModelDownloadProgress }) => void) => {
        progressHandler = handler;
        return () => {
          progressHandler = null;
        };
      },
    },
  };
}

describe("ModelDownloads", () => {
  beforeEach(() => {
    progressHandler = null;
  });

  afterEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (window as any).__TAURI__;
  });

  it("lists installed and downloadable models with their sizes", async () => {
    installTauri(async (cmd) => (cmd === "list_models" ? MODELS : undefined));
    render(<ModelDownloads />);
    expect(await screen.findByText("Ryan (American English, male)")).toBeInTheDocument();
    expect(screen.getByText("Installed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download Kokoro v1.0 (multilingual), 337 MB" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Download Lessac/ })).toBeEnabled();
  });

  it("downloads a model, shows its progress, and reloads the voices when it is installed", async () => {
    let finish: () => void = () => {};
    const installed = MODELS.map((model) => (model.id === "kokoro" ? { ...model, installed: true } : model));
    let listCalls = 0;
    const invoke = vi.fn<Invoke>(async (cmd, args) => {
      if (cmd === "list_models") return listCalls++ === 0 ? MODELS : installed;
      if (cmd === "install_model") {
        expect(args).toEqual({ model: "kokoro" });
        return new Promise<void>((resolve) => {
          finish = resolve;
        });
      }
      return undefined;
    });
    installTauri(invoke);
    const onInstalled = vi.fn();
    render(<ModelDownloads onInstalled={onInstalled} />);

    fireEvent.click(await screen.findByRole("button", { name: /Download Kokoro/ }));
    expect(screen.getByRole("button", { name: /Download Lessac/ })).toBeDisabled();
    await waitFor(() => expect(progressHandler).not.toBeNull());
    act(() => progressHandler?.({ payload: { model: "kokoro", received: 176_859_884, total: 353_719_767 } }));
    expect(screen.getByLabelText("Downloading Kokoro v1.0 (multilingual)")).toHaveValue(50);
    expect(screen.getByText("50%")).toBeInTheDocument();

    await act(async () => finish());
    expect(await screen.findByText("Kokoro v1.0 (multilingual) is installed.")).toBeInTheDocument();
    expect(onInstalled).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("Installed")).toHaveLength(2);
  });

  it("shows why a download failed and lets the user try again", async () => {
    installTauri(async (cmd) => {
      if (cmd === "list_models") return MODELS;
      if (cmd === "install_model") throw new Error("kokoro-v1.0.onnx failed its integrity check (SHA-256 mismatch); it was not installed.");
      return undefined;
    });
    const onInstalled = vi.fn();
    render(<ModelDownloads onInstalled={onInstalled} />);
    fireEvent.click(await screen.findByRole("button", { name: /Download Kokoro/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("SHA-256 mismatch");
    expect(onInstalled).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Download Kokoro/ })).toBeEnabled();
  });

  it("cancels the running download", async () => {
    const invoke = vi.fn<Invoke>(async (cmd) => {
      if (cmd === "list_models") return MODELS;
      if (cmd === "install_model") return new Promise(() => {});
      if (cmd === "cancel_model_download") return true;
      return undefined;
    });
    installTauri(invoke);
    render(<ModelDownloads />);
    fireEvent.click(await screen.findByRole("button", { name: /Download Lessac/ }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(invoke).toHaveBeenCalledWith("cancel_model_download", undefined);
  });

  it("reports when the installed models cannot be checked", async () => {
    installTauri(async () => {
      throw new Error("The model installer is missing from this installation.");
    });
    render(<ModelDownloads />);
    expect(await screen.findByRole("alert")).toHaveTextContent("model installer is missing");
  });
});

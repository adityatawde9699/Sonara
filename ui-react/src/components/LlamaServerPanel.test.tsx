import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LlamaServerPanel } from "./LlamaServerPanel";
import * as tauri from "../lib/tauri";

vi.mock("../lib/tauri", async () => {
  const actual = await vi.importActual<typeof import("../lib/tauri")>("../lib/tauri");
  return {
    ...actual,
    llamaServerExecutable: vi.fn(),
    llamaServerChooseExecutable: vi.fn(),
    llamaServerStatus: vi.fn(),
    llamaServerStart: vi.fn(),
    llamaServerStop: vi.fn(),
    llmChooseModel: vi.fn(),
  };
});

const stopped: tauri.LlamaServerStatus = { state: "stopped", logTail: [], restarts: 0 };

describe("LlamaServerPanel", () => {
  beforeEach(() => {
    vi.mocked(tauri.llamaServerExecutable).mockReset().mockResolvedValue("/usr/bin/llama-server");
    vi.mocked(tauri.llamaServerStatus).mockReset().mockResolvedValue(stopped);
    vi.mocked(tauri.llamaServerStart).mockReset().mockResolvedValue({ ...stopped, state: "ready", endpoint: "http://127.0.0.1:4321/v1" });
    vi.mocked(tauri.llamaServerStop).mockReset().mockResolvedValue(stopped);
  });

  it("starts the server with the chosen models and shows its endpoint", async () => {
    render(<LlamaServerPanel config={{ provider: "llama_cpp", managedServer: true, serverModel: "/m/chat.gguf", contextSize: 4096, threads: 0 }} onChange={vi.fn()} />);
    expect(await screen.findByText("/usr/bin/llama-server")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start server" }));
    await waitFor(() => expect(tauri.llamaServerStart).toHaveBeenCalledWith({
      model: "/m/chat.gguf", embeddingModel: undefined, contextSize: 4096, threads: undefined,
    }));
    expect(await screen.findByText("http://127.0.0.1:4321/v1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop server" }));
    await waitFor(() => expect(tauri.llamaServerStop).toHaveBeenCalled());
  });

  it("cannot start without a program or a model, and shows a failure's output", async () => {
    vi.mocked(tauri.llamaServerExecutable).mockResolvedValue(null);
    vi.mocked(tauri.llamaServerStatus).mockResolvedValue({ state: "failed", error: "llama-server kept exiting.", logTail: ["error: bad model"], restarts: 2 });
    render(<LlamaServerPanel config={{ provider: "llama_cpp", managedServer: true }} onChange={vi.fn()} />);
    expect(await screen.findByText("llama-server was not found on PATH")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start server" })).toBeDisabled();
    expect(await screen.findByText(/kept exiting/)).toBeInTheDocument();
    expect(screen.getByText("error: bad model")).toBeInTheDocument();
  });
});

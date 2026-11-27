import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ApiKeyField } from "./ApiKeyField";
import * as tauri from "../lib/tauri";

vi.mock("../lib/tauri", async () => {
  const actual = await vi.importActual<typeof import("../lib/tauri")>("../lib/tauri");
  return {
    ...actual,
    llmApiKeyStatus: vi.fn(),
    llmSetApiKey: vi.fn(),
    llmClearApiKey: vi.fn(),
  };
});

describe("ApiKeyField", () => {
  beforeEach(() => {
    vi.mocked(tauri.llmApiKeyStatus).mockReset().mockResolvedValue(null);
    vi.mocked(tauri.llmSetApiKey).mockReset().mockResolvedValue("keychain");
    vi.mocked(tauri.llmClearApiKey).mockReset().mockResolvedValue(undefined);
  });

  it("hands a key to the backend and then shows only where it is kept", async () => {
    render(<ApiKeyField provider="openai" />);
    const input = await screen.findByLabelText("API Key");
    fireEvent.change(input, { target: { value: "sk-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    await waitFor(() => expect(tauri.llmSetApiKey).toHaveBeenCalledWith("openai", "sk-secret"));
    expect(await screen.findByText("Saved in your system keychain")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("sk-secret")).not.toBeInTheDocument();
  });

  it("says when the key lasts only for this session", async () => {
    vi.mocked(tauri.llmApiKeyStatus).mockResolvedValue("session");
    render(<ApiKeyField provider="gemini" />);
    expect(await screen.findByText(/kept for this session only/)).toBeInTheDocument();
  });

  it("removes a saved key", async () => {
    vi.mocked(tauri.llmApiKeyStatus).mockResolvedValue("keychain");
    render(<ApiKeyField provider="openai" />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(tauri.llmClearApiKey).toHaveBeenCalledWith("openai"));
    expect(await screen.findByLabelText("API Key")).toHaveValue("");
  });
});

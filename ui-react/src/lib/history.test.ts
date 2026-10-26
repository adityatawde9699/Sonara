import { describe, it, expect, beforeEach } from "vitest";
import {
  getRecentDocuments,
  saveRecentDocument,
  clearRecentDocuments,
} from "./history";

describe("history storage utility", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns empty array when localStorage is empty", () => {
    expect(getRecentDocuments()).toEqual([]);
  });

  it("saves a new document and adds timestamp", () => {
    const list = saveRecentDocument({
      sourceName: "sample.pdf",
      sourceSha256: "abc12345",
      voice: "en_US-john-medium",
      chunksCount: 5,
      totalDurationSeconds: 42.5,
    });

    expect(list.length).toBe(1);
    expect(list[0].sourceName).toBe("sample.pdf");
    expect(list[0].sourceSha256).toBe("abc12345");
    expect(typeof list[0].lastListenedAt).toBe("number");

    // Reading back
    const retrieved = getRecentDocuments();
    expect(retrieved.length).toBe(1);
    expect(retrieved[0].sourceSha256).toBe("abc12345");
  });

  it("deduplicates documents by sha256 and moves latest to front", () => {
    saveRecentDocument({
      sourceName: "doc1.pdf",
      sourceSha256: "hash1",
      voice: "en_US-john-medium",
      chunksCount: 2,
      totalDurationSeconds: 10,
    });

    saveRecentDocument({
      sourceName: "doc2.pdf",
      sourceSha256: "hash2",
      voice: "en_US-john-medium",
      chunksCount: 3,
      totalDurationSeconds: 20,
    });

    // Re-open doc1
    const updated = saveRecentDocument({
      sourceName: "doc1.pdf",
      sourceSha256: "hash1",
      voice: "en_US-john-medium",
      chunksCount: 2,
      totalDurationSeconds: 10,
    });

    expect(updated.length).toBe(2);
    expect(updated[0].sourceSha256).toBe("hash1");
    expect(updated[1].sourceSha256).toBe("hash2");
  });

  it("clears document history", () => {
    saveRecentDocument({
      sourceName: "doc1.pdf",
      sourceSha256: "hash1",
      voice: "en_US-john-medium",
      chunksCount: 2,
      totalDurationSeconds: 10,
    });

    expect(getRecentDocuments().length).toBe(1);
    clearRecentDocuments();
    expect(getRecentDocuments().length).toBe(0);
  });

  it("handles corrupt localStorage data gracefully", () => {
    localStorage.setItem("sonara_recent_documents", "invalid JSON syntax {{{");
    expect(getRecentDocuments()).toEqual([]);
  });
});

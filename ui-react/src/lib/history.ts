/**
 * Utilities for persisting and retrieving recently opened documents in local storage.
 */

export interface RecentDocument {
  sourceName: string;
  sourceSha256: string;
  voice: string;
  chunksCount: number;
  totalDurationSeconds: number;
  lastListenedAt: number; // Unix timestamp ms
}

const STORAGE_KEY = "sonara_recent_documents";
const MAX_HISTORY = 10;

export function getRecentDocuments(): RecentDocument[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed.slice(0, MAX_HISTORY);
    }
  } catch {
    // Ignore storage parse errors
  }
  return [];
}

export function saveRecentDocument(doc: Omit<RecentDocument, "lastListenedAt">): RecentDocument[] {
  try {
    const existing = getRecentDocuments();
    const updated: RecentDocument = {
      ...doc,
      lastListenedAt: Date.now(),
    };
    // Remove if already exists with same SHA256
    const filtered = existing.filter((d) => d.sourceSha256 !== doc.sourceSha256);
    const nextList = [updated, ...filtered].slice(0, MAX_HISTORY);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(nextList));
    return nextList;
  } catch {
    return [];
  }
}

export function clearRecentDocuments(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore storage errors
  }
}

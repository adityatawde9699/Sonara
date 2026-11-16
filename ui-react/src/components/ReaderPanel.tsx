import { useEffect, useMemo, useRef, useState } from "react";
import { type FrontendChunk, getDocumentText, getReaderDocument } from "../lib/tauri";
import { splitAtCodePoints } from "../lib/readAlong";

const BLOCKS_PER_PAGE = 28;

interface Props {
  sourceName: string;
  sourceSha256: string;
  /** The session's passages; each may carry its source span. */
  chunks?: FrontendChunk[];
  /** Index of the passage the player is on. */
  activeChunk?: number;
  /** Start listening from a passage. */
  onPlayFromChunk?: (index: number) => void;
}

interface Block {
  id: string | null;
  text: string;
}

export function ReaderPanel({ sourceName, sourceSha256, chunks = [], activeChunk = 0, onPlayFromChunk }: Props) {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [fontScale, setFontScale] = useState(1);
  const [followAlong, setFollowAlong] = useState(true);
  const activeRef = useRef<HTMLParagraphElement | null>(null);

  const hasSpans = chunks.some((chunk) => chunk.source);

  const loadText = async () => {
    setLoading(true);
    setError("");
    try {
      let loaded: Block[] | null = null;
      if (hasSpans) {
        try {
          const document = await getReaderDocument();
          loaded = document.blocks.map((block) => ({ id: block.id, text: block.text }));
        } catch {
          loaded = null; // fall back to plain text without highlighting
        }
      }
      if (!loaded) {
        const result = await getDocumentText();
        loaded = result.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean).map((text) => ({ id: null, text }));
      }
      if (!loaded.some((block) => block.text.trim())) throw new Error("No readable text was returned for this document.");
      setBlocks(loaded);
      setPage(0);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load the extracted document text.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadText();
    // The backend exposes the text for the current desktop session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceSha256, hasSpans]);

  const blockIndexById = useMemo(() => {
    const map = new Map<string, number>();
    blocks.forEach((block, index) => {
      if (block.id) map.set(block.id, index);
    });
    return map;
  }, [blocks]);

  // The first passage of each block, for "listen from here".
  const firstChunkByBlock = useMemo(() => {
    const map = new Map<number, number>();
    chunks.forEach((chunk, index) => {
      const blockIndex = chunk.source ? blockIndexById.get(chunk.source.blockId) : undefined;
      if (blockIndex !== undefined && !map.has(blockIndex)) map.set(blockIndex, index);
    });
    return map;
  }, [blockIndexById, chunks]);

  const activeSource = chunks[activeChunk]?.source ?? null;
  const activeBlock = activeSource ? blockIndexById.get(activeSource.blockId) ?? -1 : -1;
  const synced = firstChunkByBlock.size > 0;

  const pages = Math.max(1, Math.ceil(blocks.length / BLOCKS_PER_PAGE));
  const pageBlocks = blocks.slice(page * BLOCKS_PER_PAGE, (page + 1) * BLOCKS_PER_PAGE);
  const needle = query.trim().toLocaleLowerCase();
  const matchCount = needle ? blocks.reduce((count, block) => count + (block.text.toLocaleLowerCase().includes(needle) ? 1 : 0), 0) : 0;

  useEffect(() => {
    if (!needle) return;
    const firstMatch = blocks.findIndex((block) => block.text.toLocaleLowerCase().includes(needle));
    if (firstMatch >= 0) {
      setFollowAlong(false);
      setPage(Math.floor(firstMatch / BLOCKS_PER_PAGE));
    }
  }, [blocks, needle]);

  // Follow the spoken passage across pages.
  useEffect(() => {
    if (!followAlong || activeBlock < 0) return;
    setPage(Math.floor(activeBlock / BLOCKS_PER_PAGE));
  }, [activeBlock, followAlong]);

  useEffect(() => {
    if (!followAlong || activeBlock < 0) return;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    activeRef.current?.scrollIntoView?.({ block: "center", behavior: reduceMotion ? "auto" : "smooth" });
  }, [activeBlock, activeSource?.start, followAlong, page]);

  const turnPage = (next: number) => {
    setFollowAlong(false);
    setPage(Math.min(pages - 1, Math.max(0, next)));
  };

  return (
    <section className="reader-panel" aria-labelledby="reader-title">
      <header className="reader-header">
        <div className="reader-heading-copy">
          <span className="reader-eyebrow">READING VIEW</span>
          <h2 id="reader-title" title={sourceName}>{sourceName}</h2>
          <p>
            {synced
              ? "Locally extracted text · the passage being read is highlighted"
              : "Locally extracted text · prepare speech again to highlight along with the audio"}
          </p>
        </div>
        <div className="reader-tools" aria-label="Reading controls">
          {synced && (
            <button
              type="button"
              className={`button button-secondary reader-follow ${followAlong ? "is-on" : ""}`}
              aria-pressed={followAlong}
              onClick={() => setFollowAlong((value) => !value)}
            >
              Follow along
            </button>
          )}
          <label className="reader-search" aria-label="Search in document">
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7"/><path d="m16 16 4 4"/></svg>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find in document" />
            {query && <span className="reader-match-count" aria-live="polite">{matchCount}</span>}
          </label>
          <div className="reader-type-controls" aria-label="Text size">
            <button type="button" onClick={() => setFontScale((value) => Math.max(0.9, Number((value - 0.1).toFixed(1))))} aria-label="Decrease text size" disabled={fontScale <= 0.9}>A−</button>
            <button type="button" onClick={() => setFontScale((value) => Math.min(1.4, Number((value + 0.1).toFixed(1))))} aria-label="Increase text size" disabled={fontScale >= 1.4}>A+</button>
          </div>
        </div>
      </header>

      {loading ? (
        <div className="reader-state" role="status"><span className="reader-loader" />Loading extracted text…</div>
      ) : error ? (
        <div className="reader-state reader-error" role="alert"><p>{error}</p><button className="button button-secondary" type="button" onClick={() => void loadText()}>Try again</button></div>
      ) : (
        <>
          {query && matchCount === 0 && <p className="reader-search-empty" role="status">No matches in this document.</p>}
          <article className="reader-content" style={{ "--reader-scale": fontScale } as React.CSSProperties} aria-label="Extracted document text">
            {pageBlocks.map((block, index) => {
              const blockIndex = page * BLOCKS_PER_PAGE + index;
              const matched = needle && block.text.toLocaleLowerCase().includes(needle);
              const speaking = blockIndex === activeBlock && activeSource;
              const firstChunk = firstChunkByBlock.get(blockIndex);
              const className = ["reader-paragraph", matched ? "is-search-match" : "", speaking ? "is-speaking" : ""].filter(Boolean).join(" ");
              let content: React.ReactNode = block.text;
              if (speaking) {
                const [before, spoken, after] = splitAtCodePoints(block.text, activeSource.start, activeSource.end);
                content = <>{before}<mark className="reader-spoken" aria-current="true">{spoken}</mark>{after}</>;
              }
              return (
                <p className={className} key={block.id ?? `${blockIndex}-${block.text.slice(0, 24)}`} ref={speaking ? activeRef : undefined}>
                  {firstChunk !== undefined && onPlayFromChunk && (
                    <button
                      type="button"
                      className="reader-play-from"
                      aria-label={`Listen from paragraph ${blockIndex + 1}`}
                      title="Listen from here"
                      onClick={() => {
                        setFollowAlong(true);
                        onPlayFromChunk(firstChunk);
                      }}
                    >▶</button>
                  )}
                  {content}
                </p>
              );
            })}
          </article>
          <footer className="reader-footer">
            <span>{blocks.length.toLocaleString()} paragraphs</span>
            <nav className="reader-pagination" aria-label="Document pages">
              <button className="button button-secondary" type="button" onClick={() => turnPage(page - 1)} disabled={page === 0}>Previous</button>
              <span>Section {page + 1} of {pages}</span>
              <button className="button button-secondary" type="button" onClick={() => turnPage(page + 1)} disabled={page >= pages - 1}>Next</button>
            </nav>
          </footer>
        </>
      )}
    </section>
  );
}

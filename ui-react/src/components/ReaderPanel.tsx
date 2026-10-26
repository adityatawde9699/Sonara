import { useEffect, useMemo, useState } from "react";
import { getDocumentText } from "../lib/tauri";

const BLOCKS_PER_PAGE = 28;

interface Props {
  sourceName: string;
  sourceSha256: string;
}

export function ReaderPanel({ sourceName, sourceSha256 }: Props) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [fontScale, setFontScale] = useState(1);

  const loadText = async () => {
    setLoading(true);
    setError("");
    try {
      const result = await getDocumentText();
      if (!result.trim()) throw new Error("No readable text was returned for this document.");
      setText(result);
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
  }, [sourceSha256]);

  const blocks = useMemo(
    () => text.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean),
    [text]
  );
  const pages = Math.max(1, Math.ceil(blocks.length / BLOCKS_PER_PAGE));
  const pageBlocks = blocks.slice(page * BLOCKS_PER_PAGE, (page + 1) * BLOCKS_PER_PAGE);
  const matchCount = query.trim()
    ? blocks.reduce((count, block) => count + (block.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()) ? 1 : 0), 0)
    : 0;

  useEffect(() => {
    if (!query.trim()) return;
    const firstMatch = blocks.findIndex((block) => block.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
    if (firstMatch >= 0) setPage(Math.floor(firstMatch / BLOCKS_PER_PAGE));
  }, [blocks, query]);

  return (
    <section className="reader-panel" aria-labelledby="reader-title">
      <header className="reader-header">
        <div className="reader-heading-copy">
          <span className="reader-eyebrow">READING VIEW</span>
          <h2 id="reader-title" title={sourceName}>{sourceName}</h2>
          <p>Locally extracted text · audio position is not synced to paragraphs</p>
        </div>
        <div className="reader-tools" aria-label="Reading controls">
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
              const matched = query.trim() && block.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
              return <p className={matched ? "reader-paragraph is-search-match" : "reader-paragraph"} key={`${blockIndex}-${block.slice(0, 24)}`}>{block}</p>;
            })}
          </article>
          <footer className="reader-footer">
            <span>{blocks.length.toLocaleString()} paragraphs</span>
            <nav className="reader-pagination" aria-label="Document pages">
              <button className="button button-secondary" type="button" onClick={() => setPage((current) => Math.max(0, current - 1))} disabled={page === 0}>Previous</button>
              <span>Section {page + 1} of {pages}</span>
              <button className="button button-secondary" type="button" onClick={() => setPage((current) => Math.min(pages - 1, current + 1))} disabled={page >= pages - 1}>Next</button>
            </nav>
          </footer>
        </>
      )}
    </section>
  );
}

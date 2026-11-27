//! Reader sessions (the synthesized manifest) and saved reading progress.

use crate::audio_server::AudioLookup;
use crate::voices::DEFAULT_FALLBACK_VOICE;
use crate::{make_job_id, AppState};
use serde::{Deserialize, Serialize};
use std::fs::{self, File};
use std::io::Write;
use std::path::{Component, Path, PathBuf};
use tauri::{AppHandle, Manager};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ReaderChunk {
    pub(crate) audio_file: String,
    pub(crate) duration_seconds: f64,
    pub(crate) pause_after_ms: u64,
    /// Where the passage comes from, for read-along highlighting. Sessions
    /// saved before this existed have none.
    #[serde(default)]
    pub(crate) source: Option<SourceSpan>,
    /// The narration unit this passage speaks. Saved progress names it, so a
    /// position survives a re-synthesis that renumbers passages.
    #[serde(default)]
    pub(crate) unit_id: Option<String>,
}

/// Narration unit ids are short hash-like tokens; anything else is dropped.
pub(crate) fn valid_unit_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"-_:.".contains(&byte))
}

/// Character offsets of a passage within one extracted document block.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SourceSpan {
    pub(crate) block_id: String,
    pub(crate) start: u64,
    pub(crate) end: u64,
}

impl SourceSpan {
    fn from_manifest(value: &serde_json::Value) -> Option<Self> {
        let block_id = value.get("source_block_id")?.as_str()?;
        let start = value.get("source_start")?.as_u64()?;
        let end = value.get("source_end")?.as_u64()?;
        let valid_id = !block_id.is_empty()
            && block_id.len() <= 128
            && block_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"-_:.".contains(&byte));
        (valid_id && start < end).then(|| Self {
            block_id: block_id.to_owned(),
            start,
            end,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ReaderSession {
    pub(crate) source_name: String,
    pub(crate) source_sha256: String,
    pub(crate) narration_ruleset_version: String,
    pub(crate) voice: String,
    #[serde(default = "default_engine_name")]
    pub(crate) engine: String,
    #[serde(default)]
    pub(crate) language: Option<String>,
    #[serde(default)]
    pub(crate) page_count: Option<u32>,
    pub(crate) sample_rate: u32,
    pub(crate) channels: u16,
    pub(crate) sample_width_bytes: u16,
    pub(crate) chunks: Vec<ReaderChunk>,
    /// The canonical run directory that holds this session's files. Not
    /// stored: it is wherever `session.json` was read from.
    #[serde(skip)]
    pub(crate) dir: PathBuf,
}

/// `session.json` inside a run directory.
pub(crate) const SESSION_FILE: &str = "session.json";
pub(crate) const SESSION_VERSION: u8 = 2;

#[derive(Deserialize, Serialize)]
struct SessionFile {
    version: u8,
    #[serde(flatten)]
    session: ReaderSession,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FrontendSession {
    pub(crate) source_name: String,
    pub(crate) source_sha256: String,
    pub(crate) narration_ruleset_version: String,
    pub(crate) voice: String,
    pub(crate) engine: String,
    pub(crate) sample_rate: u32,
    pub(crate) channels: u16,
    pub(crate) sample_width_bytes: u16,
    pub(crate) audio_base_url: String,
    pub(crate) chunks: Vec<FrontendChunk>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FrontendChunk {
    pub(crate) duration_seconds: f64,
    pub(crate) pause_after_ms: u64,
    pub(crate) source: Option<SourceSpan>,
    pub(crate) unit_id: Option<String>,
}

impl FrontendSession {
    pub(crate) fn from_session(session: &ReaderSession, audio_base_url: &str) -> Self {
        Self {
            source_name: session.source_name.clone(),
            source_sha256: session.source_sha256.clone(),
            narration_ruleset_version: session.narration_ruleset_version.clone(),
            voice: session.voice.clone(),
            engine: session.engine.clone(),
            sample_rate: session.sample_rate,
            channels: session.channels,
            sample_width_bytes: session.sample_width_bytes,
            audio_base_url: audio_base_url.to_owned(),
            chunks: session
                .chunks
                .iter()
                .map(FrontendChunk::from_chunk)
                .collect(),
        }
    }
}

impl FrontendChunk {
    pub(crate) fn from_chunk(chunk: &ReaderChunk) -> Self {
        Self {
            duration_seconds: chunk.duration_seconds,
            pause_after_ms: chunk.pause_after_ms,
            source: chunk.source.clone(),
            unit_id: chunk.unit_id.clone(),
        }
    }
}

pub(crate) fn default_engine_name() -> String {
    "Piper".to_owned()
}

/// Saved reading position. Version 2 adds `unitId`; version 1 files (from
/// Sonara 1.x) are still read, as version 2 without a unit id.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Progress {
    pub(crate) version: u8,
    pub(crate) source_sha256: String,
    pub(crate) segment: usize,
    pub(crate) offset_seconds: f64,
    pub(crate) playback_rate: f64,
    #[serde(default)]
    pub(crate) unit_id: Option<String>,
}

pub(crate) const PROGRESS_VERSION: u8 = 2;

/// Parse a saved progress file, upgrading version 1 in memory. A newer
/// version is an error, so this build never rewrites what it cannot read.
pub(crate) fn parse_progress(bytes: &[u8]) -> Result<Progress, String> {
    let mut progress: Progress = serde_json::from_slice(bytes)
        .map_err(|_| "Saved reading progress is invalid and was not restored.".to_owned())?;
    match progress.version {
        1 => {
            progress.version = PROGRESS_VERSION;
            progress.unit_id = None;
        }
        PROGRESS_VERSION => {}
        _ => {
            return Err(
                "Saved reading progress is from a newer version of Sonara and was not restored."
                    .to_owned(),
            )
        }
    }
    if progress
        .unit_id
        .as_deref()
        .is_some_and(|unit| !valid_unit_id(unit))
    {
        progress.unit_id = None;
    }
    Ok(progress)
}

fn read_manifest(output_dir: &Path) -> Result<serde_json::Value, String> {
    let manifest_path = output_dir.join("audio_chunks.json");
    serde_json::from_slice(
        &fs::read(&manifest_path)
            .map_err(|error| format!("Could not read the audio manifest: {error}"))?,
    )
    .map_err(|error| format!("The generated audio manifest is invalid: {error}"))
}

/// How far synthesis has got, as the manifest reports it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct ManifestProgress {
    pub(crate) completed: usize,
    /// Passages planned; equal to `completed` for a finished manifest.
    pub(crate) total: usize,
    pub(crate) complete: bool,
}

fn manifest_progress(manifest: &serde_json::Value) -> ManifestProgress {
    let chunk_count = manifest
        .get("chunks")
        .and_then(serde_json::Value::as_array)
        .map_or(0, Vec::len);
    let number = |key: &str| {
        manifest
            .get(key)
            .and_then(serde_json::Value::as_u64)
            .and_then(|value| usize::try_from(value).ok())
    };
    // Schema 1 manifests have no completion flag; they are written whole.
    let complete = manifest
        .get("complete")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(true);
    let completed = number("completed_units").unwrap_or(chunk_count);
    let total = number("total_units").unwrap_or(chunk_count).max(completed);
    ManifestProgress {
        completed,
        total,
        complete,
    }
}

/// The session metadata in a manifest, with no passages yet.
fn session_header(
    manifest: &serde_json::Value,
    source_path: &Path,
    canonical_output: PathBuf,
) -> Result<ReaderSession, String> {
    let source_name = source_path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("Document")
        .to_owned();
    let source_sha256 = manifest
        .get("document_source_sha256")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| "The audio manifest has no document identity.".to_owned())?
        .to_owned();
    validate_hash(&source_sha256)?;
    let audio_format = manifest
        .get("audio_format")
        .ok_or_else(|| "The audio manifest has no audio format.".to_owned())?;
    let format_value = |key: &str| {
        audio_format
            .get(key)
            .and_then(serde_json::Value::as_u64)
            .filter(|value| *value > 0)
    };
    let sample_rate = format_value("sample_rate")
        .and_then(|value| u32::try_from(value).ok())
        .ok_or_else(|| "The manifest sample rate is invalid.".to_owned())?;
    let channels = format_value("channels")
        .and_then(|value| u16::try_from(value).ok())
        .ok_or_else(|| "The manifest channel count is invalid.".to_owned())?;
    let sample_width_bytes = format_value("sample_width_bytes")
        .and_then(|value| u16::try_from(value).ok())
        .ok_or_else(|| "The manifest sample width is invalid.".to_owned())?;
    let text = |key: &str| manifest.get(key).and_then(serde_json::Value::as_str);
    Ok(ReaderSession {
        source_name,
        source_sha256,
        narration_ruleset_version: text("narration_ruleset_version")
            .unwrap_or("unknown")
            .to_owned(),
        voice: text("voice").unwrap_or(DEFAULT_FALLBACK_VOICE).to_owned(),
        engine: text("engine").unwrap_or("Piper").to_owned(),
        language: text("language")
            .filter(|language| language.len() <= 16)
            .map(str::to_owned),
        page_count: manifest
            .get("page_count")
            .and_then(serde_json::Value::as_u64)
            .and_then(|pages| u32::try_from(pages).ok())
            .filter(|pages| *pages > 0),
        sample_rate,
        channels,
        sample_width_bytes,
        chunks: Vec::new(),
        dir: canonical_output,
    })
}

/// Validate the manifest's passages from `start` on: each must be a file
/// inside the run directory, with a positive duration.
fn manifest_chunks(
    manifest: &serde_json::Value,
    output_dir: &Path,
    canonical_output: &Path,
    start: usize,
) -> Result<Vec<ReaderChunk>, String> {
    let chunk_values = manifest
        .get("chunks")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| "The audio manifest contains no playable chunks.".to_owned())?;
    let mut chunks = Vec::with_capacity(chunk_values.len().saturating_sub(start));
    for (index, value) in chunk_values.iter().enumerate().skip(start) {
        let audio_file = value
            .get("audio_file")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| format!("Audio passage {} has no audio file.", index + 1))?;
        let relative = Path::new(audio_file);
        if !is_safe_relative_audio_path(relative) {
            return Err(format!(
                "Audio passage {} has an unsafe local path.",
                index + 1
            ));
        }
        let canonical_file = output_dir
            .join(relative)
            .canonicalize()
            .map_err(|error| format!("Audio passage {} is unavailable: {error}", index + 1))?;
        if !canonical_file.starts_with(canonical_output) || !canonical_file.is_file() {
            return Err(format!(
                "Audio passage {} is outside Sonara's output directory.",
                index + 1
            ));
        }
        let duration_seconds = value
            .get("duration_seconds")
            .and_then(serde_json::Value::as_f64)
            .filter(|duration| duration.is_finite() && *duration > 0.0)
            .ok_or_else(|| format!("Audio passage {} has an invalid duration.", index + 1))?;
        chunks.push(ReaderChunk {
            audio_file: canonical_file.to_string_lossy().into_owned(),
            duration_seconds,
            pause_after_ms: value
                .get("pause_after_ms")
                .and_then(serde_json::Value::as_u64)
                .unwrap_or(0),
            source: SourceSpan::from_manifest(value),
            unit_id: value
                .get("unit_id")
                .and_then(serde_json::Value::as_str)
                .filter(|unit| valid_unit_id(unit))
                .map(str::to_owned),
        });
    }
    Ok(chunks)
}

/// Build the session for a finished run from its `audio_chunks.json`, and
/// save it as the run's `session.json`.
pub(crate) fn load_reader_session(
    output_dir: &Path,
    source_path: &Path,
) -> Result<ReaderSession, String> {
    let manifest = read_manifest(output_dir)?;
    if !manifest_progress(&manifest).complete {
        return Err("Speech generation stopped before the document was finished.".to_owned());
    }
    let canonical_output = output_dir
        .canonicalize()
        .map_err(|error| format!("Could not inspect generated audio: {error}"))?;
    let mut session = session_header(&manifest, source_path, canonical_output.clone())?;
    session.chunks = manifest_chunks(&manifest, output_dir, &canonical_output, 0)?;
    if session.chunks.is_empty() {
        return Err("The audio manifest contains no playable chunks.".to_owned());
    }
    save_session(&session)?;
    Ok(session)
}

/// Passages that a running synthesis has added since `previous`.
#[derive(Debug)]
pub(crate) struct PartialUpdate {
    pub(crate) session: ReaderSession,
    /// Index of the first passage not in `previous`.
    pub(crate) first_new: usize,
    pub(crate) progress: ManifestProgress,
}

/// Read a run's manifest while it is being written and extend `previous`
/// (the passages already published) with the ones that are new. Only the
/// new passages are validated. `None` until the first passage exists.
pub(crate) fn refresh_partial_session(
    output_dir: &Path,
    source_path: &Path,
    previous: Option<&ReaderSession>,
) -> Result<Option<PartialUpdate>, String> {
    let manifest = read_manifest(output_dir)?;
    let progress = manifest_progress(&manifest);
    let mut session = match previous {
        Some(previous) => {
            let sha = manifest
                .get("document_source_sha256")
                .and_then(serde_json::Value::as_str);
            if sha != Some(previous.source_sha256.as_str()) {
                return Err("The audio manifest changed document while it was written.".to_owned());
            }
            previous.clone()
        }
        None => {
            let canonical_output = output_dir
                .canonicalize()
                .map_err(|error| format!("Could not inspect generated audio: {error}"))?;
            session_header(&manifest, source_path, canonical_output)?
        }
    };
    let first_new = session.chunks.len();
    let new_chunks = manifest_chunks(&manifest, output_dir, &session.dir.clone(), first_new)?;
    if session.chunks.is_empty() && new_chunks.is_empty() {
        return Ok(None);
    }
    session.chunks.extend(new_chunks);
    Ok(Some(PartialUpdate {
        session,
        first_new,
        progress,
    }))
}

/// Write `session.json` into the session's own run directory.
pub(crate) fn save_session(session: &ReaderSession) -> Result<(), String> {
    atomic_write_json(
        &session.dir.join(SESSION_FILE),
        &SessionFile {
            version: SESSION_VERSION,
            session: session.clone(),
        },
    )
}

/// Read a run directory's `session.json`, checking that every passage is a
/// file inside that directory.
pub(crate) fn load_saved_session(run_dir: &Path) -> Option<ReaderSession> {
    let bytes = fs::read(run_dir.join(SESSION_FILE)).ok()?;
    let file: SessionFile = serde_json::from_slice(&bytes).ok()?;
    if file.version != SESSION_VERSION {
        return None;
    }
    let mut session = file.session;
    validate_hash(&session.source_sha256).ok()?;
    if session.chunks.is_empty() {
        return None;
    }
    let root = run_dir.canonicalize().ok()?;
    session.dir = root.clone();
    for chunk in &mut session.chunks {
        let path = PathBuf::from(&chunk.audio_file).canonicalize().ok()?;
        if !path.starts_with(&root)
            || !path.is_file()
            || !chunk.duration_seconds.is_finite()
            || chunk.duration_seconds <= 0.0
        {
            return None;
        }
        chunk.audio_file = path.to_string_lossy().into_owned();
    }
    Some(session)
}

pub(crate) fn progress_path(app: &AppHandle, source_sha256: &str) -> Result<PathBuf, String> {
    let root = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("Could not find Sonara's local data directory: {error}"))?
        .join("progress");
    fs::create_dir_all(&root)
        .map_err(|error| format!("Could not create progress storage: {error}"))?;
    Ok(root.join(format!("{source_sha256}.json")))
}

pub(crate) fn atomic_write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let temp = path.with_file_name(format!(
        ".{}.{}.tmp",
        path.file_name().unwrap_or_default().to_string_lossy(),
        make_job_id()
    ));
    let bytes = serde_json::to_vec_pretty(value)
        .map_err(|error| format!("Could not encode local reader state: {error}"))?;
    let result = (|| {
        let mut file = File::create(&temp)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        fs::rename(&temp, path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result.map_err(|error| format!("Could not save local reader state: {error}"))
}

pub(crate) fn validate_hash(hash: &str) -> Result<(), String> {
    if hash.len() == 64 && hash.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        Ok(())
    } else {
        Err("Document identity is invalid.".to_owned())
    }
}

pub(crate) fn is_safe_relative_audio_path(path: &Path) -> bool {
    !path.as_os_str().is_empty()
        && !path.is_absolute()
        && path
            .components()
            .all(|item| matches!(item, Component::Normal(_)))
}

/// Map an audio route to a manifest entry: of the session being
/// synthesized when it is for this document, otherwise of the open session.
/// Each lock is held only long enough to copy one path.
pub(crate) fn session_audio_lookup(
    state: &AppState,
    document_hash: &str,
    index: usize,
) -> AudioLookup {
    {
        let Ok(streaming) = state.streaming.lock() else {
            return AudioLookup::StateError;
        };
        if let Some(streaming) = streaming
            .as_ref()
            .filter(|streaming| streaming.session.source_sha256 == document_hash)
        {
            // A passage the new run has not written yet is not served from
            // an older run of the same document.
            return chunk_lookup(&streaming.session, index);
        }
    }
    let Ok(session) = state.session.lock() else {
        return AudioLookup::StateError;
    };
    match session
        .as_ref()
        .filter(|session| session.source_sha256 == document_hash)
    {
        Some(session) => chunk_lookup(session, index),
        None => AudioLookup::NotFound,
    }
}

fn chunk_lookup(session: &ReaderSession, index: usize) -> AudioLookup {
    match session.chunks.get(index) {
        Some(_) if session.dir.as_os_str().is_empty() => AudioLookup::Unavailable,
        Some(chunk) => AudioLookup::Passage {
            audio_file: PathBuf::from(&chunk.audio_file),
            chunks_root: session.dir.join("chunks"),
        },
        None => AudioLookup::NotFound,
    }
}

pub(crate) fn validate_progress_shape(progress: &Progress) -> Result<(), String> {
    if progress.version == PROGRESS_VERSION
        && progress.unit_id.as_deref().is_none_or(valid_unit_id)
        && progress.offset_seconds.is_finite()
        && progress.offset_seconds >= 0.0
        && progress.playback_rate.is_finite()
        && (0.7..=1.5).contains(&progress.playback_rate)
    {
        Ok(())
    } else {
        Err("Reading progress is outside the supported range.".to_owned())
    }
}

/// The extracted document as blocks, for the read-along view.
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ReaderDocument {
    pub(crate) source_sha256: String,
    pub(crate) blocks: Vec<ReaderBlock>,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ReaderBlock {
    pub(crate) id: String,
    pub(crate) kind: String,
    pub(crate) text: String,
}

/// Same cap as the text the assistant may read (llm_client.py).
const MAX_EXTRACTED_DOCUMENT_BYTES: u64 = 64 * 1024 * 1024;

/// Read `extracted_document.json` from the reader output, only when it is
/// the extraction of `expected_sha256` (the document of the open session).
pub(crate) fn load_reader_document(
    output_dir: &Path,
    expected_sha256: &str,
) -> Result<ReaderDocument, String> {
    let path = output_dir.join("extracted_document.json");
    let size = fs::metadata(&path)
        .map_err(|_| "The extracted text for this document is not available.".to_owned())?
        .len();
    if size > MAX_EXTRACTED_DOCUMENT_BYTES {
        return Err("The extracted document is too large to show.".to_owned());
    }
    let bytes =
        fs::read(&path).map_err(|error| format!("Could not read the extracted text: {error}"))?;
    let value: serde_json::Value = serde_json::from_slice(&bytes)
        .map_err(|_| "The extracted document is not valid JSON.".to_owned())?;
    let source_sha256 = value
        .get("source_sha256")
        .and_then(serde_json::Value::as_str)
        .unwrap_or_default();
    if source_sha256 != expected_sha256 {
        return Err("The extracted text belongs to a different document.".to_owned());
    }
    let blocks = value
        .get("blocks")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| "The extracted document has no text blocks.".to_owned())?
        .iter()
        .filter_map(|block| {
            Some(ReaderBlock {
                id: block.get("id")?.as_str()?.to_owned(),
                kind: block
                    .get("kind")
                    .and_then(serde_json::Value::as_str)
                    .unwrap_or("paragraph")
                    .to_owned(),
                text: block.get("text")?.as_str()?.to_owned(),
            })
        })
        .collect();
    Ok(ReaderDocument {
        source_sha256: source_sha256.to_owned(),
        blocks,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reader_document_matches_the_session_hash() {
        let root = std::env::temp_dir().join(format!("sonara-reader-doc-{}", make_job_id()));
        fs::create_dir_all(&root).unwrap();
        let sha = "c".repeat(64);
        fs::write(
            root.join("extracted_document.json"),
            serde_json::json!({
                "source_sha256": sha,
                "blocks": [
                    {"id": "b-0", "kind": "heading", "text": "Title"},
                    {"id": "b-1", "kind": "paragraph", "text": "Body."},
                    {"kind": "paragraph", "text": "no id: skipped"},
                ],
            })
            .to_string(),
        )
        .unwrap();
        let document = load_reader_document(&root, &sha).unwrap();
        assert_eq!(document.blocks.len(), 2);
        assert_eq!(document.blocks[0].kind, "heading");
        assert!(load_reader_document(&root, &"d".repeat(64)).is_err());
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn manifest_source_spans_are_validated() {
        let span = |value: serde_json::Value| SourceSpan::from_manifest(&value);
        assert_eq!(
            span(
                serde_json::json!({"source_block_id": "p1-b2", "source_start": 0, "source_end": 9})
            ),
            Some(SourceSpan {
                block_id: "p1-b2".to_owned(),
                start: 0,
                end: 9
            })
        );
        assert_eq!(
            span(serde_json::json!({"source_block_id": "x", "source_start": 4, "source_end": 4})),
            None
        );
        assert_eq!(
            span(
                serde_json::json!({"source_block_id": "../x y", "source_start": 0, "source_end": 1})
            ),
            None
        );
        assert_eq!(span(serde_json::json!({"duration_seconds": 1.0})), None);
    }

    #[test]
    fn progress_requires_supported_rate_and_document_hash() {
        assert!(validate_hash(&"a".repeat(64)).is_ok());
        assert!(validate_hash("not-a-hash").is_err());
        let progress = Progress {
            version: PROGRESS_VERSION,
            source_sha256: "a".repeat(64),
            segment: 0,
            offset_seconds: 2.0,
            playback_rate: 1.0,
            unit_id: Some("u-0001".to_owned()),
        };
        assert!(validate_progress_shape(&progress).is_ok());
        let invalid = Progress {
            playback_rate: 2.0,
            ..progress.clone()
        };
        assert!(validate_progress_shape(&invalid).is_err());
        let bad_unit = Progress {
            unit_id: Some("../x y".to_owned()),
            ..progress.clone()
        };
        assert!(validate_progress_shape(&bad_unit).is_err());
        let old = Progress {
            version: 1,
            ..progress
        };
        assert!(validate_progress_shape(&old).is_err());
    }

    #[test]
    fn version_one_progress_is_read_and_newer_versions_are_refused() {
        let v1 = serde_json::json!({
            "version": 1, "sourceSha256": "a".repeat(64), "segment": 3,
            "offsetSeconds": 1.5, "playbackRate": 1.1
        });
        let progress = parse_progress(v1.to_string().as_bytes()).unwrap();
        assert_eq!(progress.version, PROGRESS_VERSION);
        assert_eq!(progress.segment, 3);
        assert_eq!(progress.unit_id, None);

        let v2 = serde_json::json!({
            "version": 2, "sourceSha256": "a".repeat(64), "segment": 3,
            "offsetSeconds": 1.5, "playbackRate": 1.1, "unitId": "u-7"
        });
        assert_eq!(
            parse_progress(v2.to_string().as_bytes())
                .unwrap()
                .unit_id
                .as_deref(),
            Some("u-7")
        );
        let v3 = serde_json::json!({
            "version": 3, "sourceSha256": "a".repeat(64), "segment": 0,
            "offsetSeconds": 0.0, "playbackRate": 1.0
        });
        assert!(parse_progress(v3.to_string().as_bytes())
            .unwrap_err()
            .contains("newer version"));
        assert!(parse_progress(b"{nope").is_err());
    }

    fn write_run(root: &Path, complete: Option<bool>) {
        let chunks = root.join("chunks/run");
        fs::create_dir_all(&chunks).unwrap();
        fs::write(chunks.join("chunk-000000.wav"), b"RIFF").unwrap();
        let mut manifest = serde_json::json!({
            "schema_version": 2,
            "document_source_sha256": "e".repeat(64),
            "narration_ruleset_version": "rules",
            "engine": "Piper",
            "voice": "en_US-test-medium",
            "language": "en",
            "page_count": 4,
            "audio_format": {"sample_rate": 22050, "channels": 1, "sample_width_bytes": 2},
            "chunks": [{
                "unit_id": "u-0", "source_block_id": "b-0", "source_start": 0,
                "source_end": 5, "pause_after_ms": 200, "duration_seconds": 1.25,
                "audio_file": "chunks/run/chunk-000000.wav"
            }],
        });
        if let Some(complete) = complete {
            manifest["complete"] = serde_json::Value::Bool(complete);
        }
        fs::write(root.join("audio_chunks.json"), manifest.to_string()).unwrap();
    }

    #[test]
    fn a_finished_run_saves_a_versioned_session_that_reloads_from_its_directory() {
        let root = std::env::temp_dir().join(format!("sonara-run-{}", make_job_id()));
        write_run(&root, Some(true));
        let session = load_reader_session(&root, Path::new("/docs/report.pdf")).unwrap();
        assert_eq!(session.source_name, "report.pdf");
        assert_eq!(session.page_count, Some(4));
        assert_eq!(session.language.as_deref(), Some("en"));
        assert_eq!(session.chunks[0].unit_id.as_deref(), Some("u-0"));
        assert_eq!(session.dir, root.canonicalize().unwrap());

        let stored: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join(SESSION_FILE)).unwrap()).unwrap();
        assert_eq!(stored["version"], SESSION_VERSION);
        assert!(stored.get("dir").is_none());

        let reloaded = load_saved_session(&root).unwrap();
        assert_eq!(reloaded.dir, session.dir);
        assert_eq!(reloaded.chunks.len(), 1);

        // A chunk that has gone missing makes the saved session unusable.
        fs::remove_file(root.join("chunks/run/chunk-000000.wav")).unwrap();
        assert!(load_saved_session(&root).is_none());
        let _ = fs::remove_dir_all(&root);
    }

    /// A run part-way through: `ready` of `total` passages written.
    fn write_partial_run(root: &Path, sha: &str, ready: usize, total: usize) {
        let chunks_dir = root.join("chunks/run");
        fs::create_dir_all(&chunks_dir).unwrap();
        let chunks: Vec<_> = (0..ready)
            .map(|index| {
                let name = format!("chunk-{index:06}.wav");
                fs::write(chunks_dir.join(&name), b"RIFF").unwrap();
                serde_json::json!({
                    "unit_id": format!("u-{index}"), "pause_after_ms": 0,
                    "duration_seconds": 1.0 + index as f64,
                    "audio_file": format!("chunks/run/{name}")
                })
            })
            .collect();
        let manifest = serde_json::json!({
            "schema_version": 2, "document_source_sha256": sha, "engine": "Piper",
            "voice": "en_US-test-medium",
            "audio_format": {"sample_rate": 22050, "channels": 1, "sample_width_bytes": 2},
            "total_units": total, "completed_units": ready, "complete": ready == total,
            "chunks": chunks,
        });
        fs::write(root.join("audio_chunks.json"), manifest.to_string()).unwrap();
    }

    #[test]
    fn a_streaming_run_is_extended_one_batch_of_passages_at_a_time() {
        let root = std::env::temp_dir().join(format!("sonara-stream-{}", make_job_id()));
        fs::create_dir_all(&root).unwrap();
        let source = Path::new("/docs/long.pdf");
        let sha = "a1".repeat(32);
        // Before the first passage there is no manifest to read.
        assert!(refresh_partial_session(&root, source, None).is_err());
        write_partial_run(&root, &sha, 0, 5);
        assert!(refresh_partial_session(&root, source, None)
            .unwrap()
            .is_none());

        write_partial_run(&root, &sha, 2, 5);
        let first = refresh_partial_session(&root, source, None)
            .unwrap()
            .unwrap();
        assert_eq!(first.first_new, 0);
        assert_eq!(first.session.chunks.len(), 2);
        assert_eq!(
            first.progress,
            ManifestProgress {
                completed: 2,
                total: 5,
                complete: false
            }
        );
        assert!(
            !root.join(SESSION_FILE).exists(),
            "a partial run is not saved"
        );

        write_partial_run(&root, &sha, 4, 5);
        let second = refresh_partial_session(&root, source, Some(&first.session))
            .unwrap()
            .unwrap();
        assert_eq!(second.first_new, 2);
        assert_eq!(second.session.chunks.len(), 4);
        assert_eq!(second.session.chunks[3].unit_id.as_deref(), Some("u-3"));

        // A manifest for another document is refused, not merged.
        write_partial_run(&root, &"b2".repeat(32), 4, 5);
        assert!(refresh_partial_session(&root, source, Some(&second.session)).is_err());

        write_partial_run(&root, &sha, 5, 5);
        let done = load_reader_session(&root, source).unwrap();
        assert_eq!(done.chunks.len(), 5);
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn audio_for_a_streaming_document_comes_only_from_the_new_run() {
        let root = std::env::temp_dir().join(format!("sonara-stream-lookup-{}", make_job_id()));
        let (old_run, new_run) = (root.join("old"), root.join("new"));
        fs::create_dir_all(&old_run).unwrap();
        fs::create_dir_all(&new_run).unwrap();
        let sha = "c3".repeat(32);
        write_partial_run(&old_run, &sha, 3, 3);
        write_partial_run(&new_run, &sha, 1, 3);
        let source = Path::new("/docs/a.pdf");
        let state = AppState::default();
        *state.session.lock().unwrap() = Some(load_reader_session(&old_run, source).unwrap());
        let streaming = refresh_partial_session(&new_run, source, None)
            .unwrap()
            .unwrap();
        *state.streaming.lock().unwrap() = Some(crate::StreamingSession {
            job_id: "job".to_owned(),
            total_chunks: 3,
            session: streaming.session,
        });

        match session_audio_lookup(&state, &sha, 0) {
            AudioLookup::Passage { chunks_root, .. } => {
                assert!(chunks_root.starts_with(new_run.canonicalize().unwrap()));
            }
            _ => panic!("the ready passage is served from the streaming run"),
        }
        // Passage 2 exists only in the old run; it must not be served.
        assert!(matches!(
            session_audio_lookup(&state, &sha, 2),
            AudioLookup::NotFound
        ));

        *state.streaming.lock().unwrap() = None;
        assert!(matches!(
            session_audio_lookup(&state, &sha, 2),
            AudioLookup::Passage { .. }
        ));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn an_unfinished_manifest_is_not_a_session() {
        let root = std::env::temp_dir().join(format!("sonara-partial-{}", make_job_id()));
        write_run(&root, Some(false));
        assert!(load_reader_session(&root, Path::new("/docs/a.pdf")).is_err());
        assert!(!root.join(SESSION_FILE).exists());
        // Schema 1 manifests carry no flag and were always written whole.
        write_run(&root, None);
        assert!(load_reader_session(&root, Path::new("/docs/a.pdf")).is_ok());
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn manifest_paths_cannot_escape_output_root() {
        let path = Path::new("chunks/../../outside.wav");
        assert!(!is_safe_relative_audio_path(path));
        assert!(is_safe_relative_audio_path(Path::new(
            "chunks/run/chunk.wav"
        )));
        assert!(!is_safe_relative_audio_path(Path::new("")));
    }

    #[test]
    fn progress_file_round_trips_through_atomic_storage() {
        let root = std::env::temp_dir().join(format!("sonara-progress-{}", make_job_id()));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("progress.json");
        let progress = Progress {
            version: PROGRESS_VERSION,
            source_sha256: "f".repeat(64),
            segment: 4,
            offset_seconds: 12.75,
            playback_rate: 1.2,
            unit_id: None,
        };
        atomic_write_json(&path, &progress).unwrap();
        let restored: Progress = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(restored.segment, 4);
        assert_eq!(restored.offset_seconds, 12.75);
        assert_eq!(restored.playback_rate, 1.2);
        let _ = fs::remove_dir_all(root);
    }
}

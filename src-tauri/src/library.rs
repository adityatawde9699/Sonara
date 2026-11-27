//! The document library: documents prepared on this device, with the source
//! path of each, so a past document can be reopened without the file picker.
//!
//! Rust owns the paths. The frontend sees names and listening metadata and
//! refers to an entry only by its document hash, so it still cannot ask the
//! backend to open an arbitrary path. Reopening runs the stored path through
//! the same `validate_document` check as the picker.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::session::{atomic_write_json, validate_hash, ReaderSession};

pub(crate) const LIBRARY_FILE: &str = "library.json";
/// 2 adds `createdAt`, `pageCount`, `language` and `complete`. Version 1
/// files from Sonara 1.x are upgraded when read.
pub(crate) const LIBRARY_VERSION: u8 = 2;
const MAX_LIBRARY_ENTRIES: usize = 50;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LibraryEntry {
    pub(crate) source_sha256: String,
    pub(crate) source_name: String,
    pub(crate) source_path: PathBuf,
    pub(crate) voice: String,
    pub(crate) engine: String,
    pub(crate) chunks_count: usize,
    pub(crate) total_duration_seconds: f64,
    /// Unix time in milliseconds.
    pub(crate) last_listened_at: u64,
    /// When the document was first prepared, in Unix milliseconds.
    #[serde(default)]
    pub(crate) created_at: u64,
    #[serde(default)]
    pub(crate) page_count: Option<u32>,
    #[serde(default)]
    pub(crate) language: Option<String>,
    /// False for a document whose audio was only partly prepared.
    #[serde(default = "default_complete")]
    pub(crate) complete: bool,
}

fn default_complete() -> bool {
    true
}

/// What the frontend sees: no path, plus whether the file is still there.
#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LibraryDocument {
    source_sha256: String,
    source_name: String,
    voice: String,
    engine: String,
    chunks_count: usize,
    total_duration_seconds: f64,
    last_listened_at: u64,
    created_at: u64,
    page_count: Option<u32>,
    language: Option<String>,
    complete: bool,
    available: bool,
}

#[derive(Debug, Deserialize, Serialize)]
struct LibraryFile {
    version: u8,
    entries: Vec<LibraryEntry>,
}

pub(crate) fn now_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| {
            u64::try_from(elapsed.as_millis()).unwrap_or(u64::MAX)
        })
}

pub(crate) const NEWER_LIBRARY: &str =
    "Your library was saved by a newer version of Sonara. Update Sonara to see it; it has not been changed.";

/// Read the library, dropping anything malformed. A missing or corrupt file
/// is an empty library, never an error the user has to clear. A library
/// from a newer Sonara is an error, so it is not overwritten.
pub(crate) fn load_library(path: &Path) -> Result<Vec<LibraryEntry>, String> {
    let Ok(bytes) = fs::read(path) else {
        return Ok(Vec::new());
    };
    let Ok(file) = serde_json::from_slice::<LibraryFile>(&bytes) else {
        return Ok(Vec::new());
    };
    if file.version > LIBRARY_VERSION {
        return Err(NEWER_LIBRARY.to_owned());
    }
    let upgrading = file.version < LIBRARY_VERSION;
    Ok(file
        .entries
        .into_iter()
        .filter(|entry| {
            validate_hash(&entry.source_sha256).is_ok()
                && entry.source_path.is_absolute()
                && entry.total_duration_seconds.is_finite()
                && entry.total_duration_seconds >= 0.0
        })
        .map(|mut entry| {
            if upgrading || entry.created_at == 0 {
                entry.created_at = entry.last_listened_at;
            }
            if entry
                .language
                .as_deref()
                .is_some_and(|lang| lang.len() > 16)
            {
                entry.language = None;
            }
            entry
        })
        .take(MAX_LIBRARY_ENTRIES)
        .collect())
}

/// The version recorded in a library file, if it has one.
pub(crate) fn stored_version(path: &Path) -> Option<u8> {
    let value: serde_json::Value = serde_json::from_slice(&fs::read(path).ok()?).ok()?;
    u8::try_from(value.get("version")?.as_u64()?).ok()
}

/// Rewrite a version 1 library as version 2, keeping a copy of the
/// original beside it. Does nothing for any other version.
pub(crate) fn upgrade_library_file(path: &Path) -> Result<(), String> {
    if stored_version(path) != Some(1) {
        return Ok(());
    }
    let backup = path.with_extension("json.v1.bak");
    if !backup.exists() {
        fs::copy(path, &backup)
            .map_err(|error| format!("Could not back up the library: {error}"))?;
    }
    let entries = load_library(path)?;
    save_library(path, entries)
}

fn save_library(path: &Path, entries: Vec<LibraryEntry>) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("Could not create the library directory: {error}"))?;
    }
    atomic_write_json(
        path,
        &LibraryFile {
            version: LIBRARY_VERSION,
            entries,
        },
    )
}

/// Add or refresh the entry for a finished session, most recent first.
pub(crate) fn record_session(
    path: &Path,
    session: &ReaderSession,
    source_path: &Path,
    now: u64,
) -> Result<(), String> {
    let existing = load_library(path)?;
    let created_at = existing
        .iter()
        .find(|old| old.source_sha256 == session.source_sha256)
        .map_or(now, |old| old.created_at);
    let entry = LibraryEntry {
        source_sha256: session.source_sha256.clone(),
        source_name: session.source_name.clone(),
        source_path: source_path.to_path_buf(),
        voice: session.voice.clone(),
        engine: session.engine.clone(),
        chunks_count: session.chunks.len(),
        total_duration_seconds: session
            .chunks
            .iter()
            .map(|chunk| chunk.duration_seconds)
            .sum(),
        last_listened_at: now,
        created_at,
        page_count: session.page_count,
        language: session.language.clone(),
        complete: true,
    };
    // A file edited since it was last prepared has a new hash but the same
    // path; keep only the newest entry for each.
    let mut entries: Vec<_> = existing
        .into_iter()
        .filter(|old| old.source_sha256 != entry.source_sha256 && old.source_path != source_path)
        .collect();
    entries.insert(0, entry);
    entries.truncate(MAX_LIBRARY_ENTRIES);
    save_library(path, entries)
}

pub(crate) fn find_source_path(
    path: &Path,
    source_sha256: &str,
) -> Result<Option<PathBuf>, String> {
    Ok(load_library(path)?
        .into_iter()
        .find(|entry| entry.source_sha256 == source_sha256)
        .map(|entry| entry.source_path))
}

pub(crate) fn remove_entry(path: &Path, source_sha256: &str) -> Result<(), String> {
    let entries = load_library(path)?
        .into_iter()
        .filter(|entry| entry.source_sha256 != source_sha256)
        .collect();
    save_library(path, entries)
}

pub(crate) fn clear_library(path: &Path) -> Result<(), String> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(format!("Could not clear the library: {error}")),
    }
}

pub(crate) fn library_documents(entries: Vec<LibraryEntry>) -> Vec<LibraryDocument> {
    entries
        .into_iter()
        .map(|entry| LibraryDocument {
            available: entry.source_path.is_file(),
            source_sha256: entry.source_sha256,
            source_name: entry.source_name,
            voice: entry.voice,
            engine: entry.engine,
            chunks_count: entry.chunks_count,
            total_duration_seconds: entry.total_duration_seconds,
            last_listened_at: entry.last_listened_at,
            created_at: entry.created_at,
            page_count: entry.page_count,
            language: entry.language,
            complete: entry.complete,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::make_job_id;
    use crate::session::ReaderChunk;

    struct Scratch(PathBuf);

    impl Scratch {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!("sonara-library-{}", make_job_id()));
            fs::create_dir_all(&root).unwrap();
            Self(root)
        }
        fn library(&self) -> PathBuf {
            self.0.join(LIBRARY_FILE)
        }
        fn document(&self, name: &str) -> PathBuf {
            let path = self.0.join(name);
            fs::write(&path, b"text").unwrap();
            path
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn session(hash: &str, name: &str) -> ReaderSession {
        ReaderSession {
            source_name: name.to_owned(),
            source_sha256: hash.to_owned(),
            narration_ruleset_version: "rules-test".to_owned(),
            voice: "en_US-ryan-medium".to_owned(),
            engine: "Piper".to_owned(),
            language: Some("en".to_owned()),
            page_count: Some(2),
            sample_rate: 22050,
            channels: 1,
            sample_width_bytes: 2,
            chunks: [1.5, 2.5]
                .into_iter()
                .map(|duration_seconds| ReaderChunk {
                    audio_file: "/unused.wav".to_owned(),
                    duration_seconds,
                    pause_after_ms: 0,
                    source: None,
                    unit_id: None,
                })
                .collect(),
            dir: PathBuf::new(),
        }
    }

    #[test]
    fn recorded_documents_are_listed_newest_first_and_found_by_hash() {
        let scratch = Scratch::new();
        let library = scratch.library();
        let (first, second) = ("aa".repeat(32), "bb".repeat(32));
        let first_path = scratch.document("first.txt");
        record_session(&library, &session(&first, "first.txt"), &first_path, 1).unwrap();
        record_session(
            &library,
            &session(&second, "second.txt"),
            &scratch.document("second.txt"),
            2,
        )
        .unwrap();
        // Preparing the first again moves it back to the top.
        record_session(&library, &session(&first, "first.txt"), &first_path, 3).unwrap();

        let documents = library_documents(load_library(&library).unwrap());
        let names: Vec<_> = documents
            .iter()
            .map(|doc| doc.source_name.as_str())
            .collect();
        assert_eq!(names, ["first.txt", "second.txt"]);
        assert_eq!(documents[0].chunks_count, 2);
        assert_eq!(documents[0].total_duration_seconds, 4.0);
        assert_eq!(documents[0].last_listened_at, 3);
        // Re-preparing keeps the date the document was first added.
        assert_eq!(documents[0].created_at, 1);
        assert_eq!(documents[0].page_count, Some(2));
        assert!(documents[0].complete);
        assert!(documents.iter().all(|doc| doc.available));
        assert_eq!(
            find_source_path(&library, &first).unwrap(),
            Some(first_path)
        );
        assert_eq!(find_source_path(&library, &"cc".repeat(32)).unwrap(), None);
        // The frontend view never carries the path.
        let json = serde_json::to_string(&documents).unwrap();
        assert!(!json.contains("sourcePath"));
        assert!(!json.contains(scratch.0.to_str().unwrap()));
    }

    #[test]
    fn an_edited_file_replaces_its_old_entry_and_moved_files_are_unavailable() {
        let scratch = Scratch::new();
        let library = scratch.library();
        let path = scratch.document("notes.md");
        record_session(&library, &session(&"aa".repeat(32), "notes.md"), &path, 1).unwrap();
        record_session(&library, &session(&"bb".repeat(32), "notes.md"), &path, 2).unwrap();
        let entries = load_library(&library).unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].source_sha256, "bb".repeat(32));

        fs::remove_file(&path).unwrap();
        assert!(!library_documents(load_library(&library).unwrap())[0].available);
    }

    #[test]
    fn the_library_is_capped_and_survives_corruption() {
        let scratch = Scratch::new();
        let library = scratch.library();
        for index in 0..(MAX_LIBRARY_ENTRIES + 5) {
            let name = format!("doc-{index}.txt");
            let hash = format!("{index:064x}");
            record_session(
                &library,
                &session(&hash, &name),
                &scratch.document(&name),
                index as u64,
            )
            .unwrap();
        }
        let entries = load_library(&library).unwrap();
        assert_eq!(entries.len(), MAX_LIBRARY_ENTRIES);
        assert_eq!(
            entries[0].source_name,
            format!("doc-{}.txt", MAX_LIBRARY_ENTRIES + 4)
        );

        remove_entry(&library, &entries[0].source_sha256).unwrap();
        assert_eq!(
            load_library(&library).unwrap().len(),
            MAX_LIBRARY_ENTRIES - 1
        );

        fs::write(&library, b"{not json").unwrap();
        assert!(load_library(&library).unwrap().is_empty());
        // A bad hash or a relative path is dropped rather than trusted.
        fs::write(
            &library,
            serde_json::json!({"version": 1, "entries": [{
                "sourceSha256": "../../etc", "sourceName": "x", "sourcePath": "relative.txt",
                "voice": "v", "engine": "Piper", "chunksCount": 1,
                "totalDurationSeconds": 1.0, "lastListenedAt": 0
            }]})
            .to_string(),
        )
        .unwrap();
        assert!(load_library(&library).unwrap().is_empty());

        clear_library(&library).unwrap();
        clear_library(&library).unwrap();
        assert!(!library.exists());
    }

    fn v1_library(scratch: &Scratch) -> serde_json::Value {
        serde_json::json!({"version": 1, "entries": [{
            "sourceSha256": "aa".repeat(32), "sourceName": "old.pdf",
            "sourcePath": scratch.document("old.pdf"), "voice": "en_US-ryan-medium",
            "engine": "Piper", "chunksCount": 7, "totalDurationSeconds": 42.0,
            "lastListenedAt": 1_700_000_000_000_u64
        }]})
    }

    #[test]
    fn a_version_one_library_is_upgraded_with_a_backup() {
        let scratch = Scratch::new();
        let library = scratch.library();
        let original = v1_library(&scratch).to_string();
        fs::write(&library, &original).unwrap();

        // Readable before the upgrade, as version 2 data.
        let entries = load_library(&library).unwrap();
        assert_eq!(entries[0].created_at, 1_700_000_000_000);
        assert!(entries[0].complete);
        assert_eq!(entries[0].page_count, None);

        upgrade_library_file(&library).unwrap();
        assert_eq!(stored_version(&library), Some(LIBRARY_VERSION));
        let backup = library.with_extension("json.v1.bak");
        assert_eq!(fs::read_to_string(&backup).unwrap(), original);
        assert_eq!(load_library(&library).unwrap(), entries);
        // Running it again changes nothing.
        upgrade_library_file(&library).unwrap();
        assert_eq!(fs::read_to_string(&backup).unwrap(), original);
        assert_eq!(load_library(&library).unwrap(), entries);
    }

    #[test]
    fn a_newer_library_is_refused_and_left_untouched() {
        let scratch = Scratch::new();
        let library = scratch.library();
        let mut newer = v1_library(&scratch);
        newer["version"] = serde_json::json!(3);
        let original = newer.to_string();
        fs::write(&library, &original).unwrap();

        assert_eq!(load_library(&library).unwrap_err(), NEWER_LIBRARY);
        let path = scratch.document("new.txt");
        assert!(record_session(&library, &session(&"bb".repeat(32), "new.txt"), &path, 5).is_err());
        assert!(remove_entry(&library, &"aa".repeat(32)).is_err());
        upgrade_library_file(&library).unwrap();
        assert_eq!(fs::read_to_string(&library).unwrap(), original);
    }
}

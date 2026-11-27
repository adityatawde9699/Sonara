//! One-time upgrade of Sonara 1.x local data to the version 2 layout
//! described in `storage.rs`.
//!
//! Every step can be repeated, and `data-version` is written last, so a
//! migration that is interrupted simply runs again on the next launch.
//! Version 1 progress files need no rewrite: they are read as version 2.

use std::fs;
use std::path::{Path, PathBuf};

use crate::library::{self, LIBRARY_FILE};
use crate::session::{
    is_safe_relative_audio_path, load_saved_session, save_session, validate_hash, ReaderSession,
};
use crate::storage::{
    audio_cache_dir, sessions_dir, set_current_session, DATA_VERSION, DATA_VERSION_FILE,
};

const LEGACY_OUTPUT_DIR: &str = "reader-output";
const LEGACY_CACHE_DIR: &str = ".sonara-audio-cache";
const LEGACY_SESSION_FILE: &str = "desktop-session.json";
/// The run directory the 1.x session moves into.
pub(crate) const MIGRATED_RUN_ID: &str = "migrated-v1";
/// 1.x files a version 2 session does not use.
const LEGACY_DISCARDED_FILES: &[&str] = &["speech.wav", "index.html", LEGACY_SESSION_FILE];

/// What a startup migration did, for the log.
#[derive(Debug, Default, PartialEq, Eq)]
pub(crate) struct MigrationReport {
    pub(crate) already_current: bool,
    pub(crate) library_upgraded: bool,
    pub(crate) cache_moved: bool,
    pub(crate) session_kept: bool,
}

pub(crate) fn migrate_to_v2(app_data: &Path) -> Result<MigrationReport, String> {
    let mut report = MigrationReport::default();
    match fs::read_to_string(app_data.join(DATA_VERSION_FILE)) {
        Ok(text) => {
            let version: u32 = text
                .trim()
                .parse()
                .map_err(|_| "Sonara's data-version file is unreadable.".to_owned())?;
            if version > DATA_VERSION {
                return Err(format!(
                    "Sonara's local data is version {version}, newer than this build supports ({DATA_VERSION})."
                ));
            }
            if version == DATA_VERSION {
                report.already_current = true;
                return Ok(report);
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(format!("Could not read Sonara's data version: {error}")),
    }
    fs::create_dir_all(app_data)
        .map_err(|error| format!("Could not open Sonara's local data directory: {error}"))?;

    let library_path = app_data.join(LIBRARY_FILE);
    if library::stored_version(&library_path) == Some(1) {
        library::upgrade_library_file(&library_path)?;
        report.library_upgraded = true;
    }

    let legacy = app_data.join(LEGACY_OUTPUT_DIR);
    let legacy_cache = legacy.join(LEGACY_CACHE_DIR);
    let cache = audio_cache_dir(app_data);
    if legacy_cache.is_dir() && !cache.exists() {
        fs::rename(&legacy_cache, &cache)
            .map_err(|error| format!("Could not move the audio cache: {error}"))?;
        report.cache_moved = true;
    }

    report.session_kept = migrate_legacy_session(app_data, &legacy)?;
    if legacy.exists() {
        fs::remove_dir_all(&legacy)
            .map_err(|error| format!("Could not remove Sonara 1.x audio files: {error}"))?;
    }

    fs::write(app_data.join(DATA_VERSION_FILE), DATA_VERSION.to_string())
        .map_err(|error| format!("Could not record Sonara's data version: {error}"))?;
    Ok(report)
}

/// Move the 1.x session (if it is whole) into `sessions/migrated-v1`, so
/// "Continue listening" still works after the upgrade. Returns whether a
/// session was kept.
fn migrate_legacy_session(app_data: &Path, legacy: &Path) -> Result<bool, String> {
    let run_dir = sessions_dir(app_data).join(MIGRATED_RUN_ID);
    if !run_dir.exists() {
        let Some(old_root) = legacy
            .join(LEGACY_SESSION_FILE)
            .is_file()
            .then(|| legacy.canonicalize().ok())
            .flatten()
        else {
            return Ok(false);
        };
        fs::create_dir_all(sessions_dir(app_data))
            .map_err(|error| format!("Could not create the sessions directory: {error}"))?;
        fs::rename(legacy, &run_dir)
            .map_err(|error| format!("Could not move the last session: {error}"))?;
        // Remember where the paths in desktop-session.json pointed.
        fs::write(
            run_dir.join(".legacy-root"),
            old_root.to_string_lossy().as_bytes(),
        )
        .map_err(|error| format!("Could not move the last session: {error}"))?;
    }
    if load_saved_session(&run_dir).is_none() {
        let Some(session) = rebase_legacy_session(&run_dir) else {
            // Partial or unreadable: nothing worth keeping.
            let _ = fs::remove_dir_all(&run_dir);
            return Ok(false);
        };
        save_session(&session)?;
    }
    // After an interrupted migration the 1.x cache can have moved along
    // with the session; it belongs in audio-cache/.
    let stray_cache = run_dir.join(LEGACY_CACHE_DIR);
    if stray_cache.is_dir() {
        let cache = audio_cache_dir(app_data);
        if cache.exists() || fs::rename(&stray_cache, &cache).is_err() {
            let _ = fs::remove_dir_all(&stray_cache);
        }
    }
    for name in LEGACY_DISCARDED_FILES.iter().chain(&[".legacy-root"]) {
        let _ = fs::remove_file(run_dir.join(name));
    }
    set_current_session(app_data, &run_dir)?;
    Ok(true)
}

/// Read the 1.x `desktop-session.json` from its new place, pointing each
/// passage at the same file under `run_dir`. Every passage must exist.
fn rebase_legacy_session(run_dir: &Path) -> Option<ReaderSession> {
    let bytes = fs::read(run_dir.join(LEGACY_SESSION_FILE)).ok()?;
    let mut session: ReaderSession = serde_json::from_slice(&bytes).ok()?;
    validate_hash(&session.source_sha256).ok()?;
    if session.chunks.is_empty() {
        return None;
    }
    let old_root = PathBuf::from(fs::read_to_string(run_dir.join(".legacy-root")).ok()?);
    let new_root = run_dir.canonicalize().ok()?;
    for chunk in &mut session.chunks {
        let relative = Path::new(&chunk.audio_file)
            .strip_prefix(&old_root)
            .ok()?
            .to_path_buf();
        if !is_safe_relative_audio_path(&relative) || !relative.starts_with("chunks") {
            return None;
        }
        let file = new_root.join(&relative).canonicalize().ok()?;
        if !file.starts_with(&new_root)
            || !file.is_file()
            || !chunk.duration_seconds.is_finite()
            || chunk.duration_seconds <= 0.0
        {
            return None;
        }
        chunk.audio_file = file.to_string_lossy().into_owned();
    }
    session.dir = new_root;
    Some(session)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::make_job_id;
    use crate::storage::load_current_session;

    struct Scratch(PathBuf);

    impl Scratch {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!("sonara-migrate-{}", make_job_id()));
            fs::create_dir_all(&root).unwrap();
            Self(root.canonicalize().unwrap())
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    /// A Sonara 1.x data directory with one finished session.
    fn seed_v1(root: &Path) {
        let legacy = root.join(LEGACY_OUTPUT_DIR);
        let chunk_dir = legacy.join("chunks").join("ab".repeat(32)).join("run");
        fs::create_dir_all(&chunk_dir).unwrap();
        fs::create_dir_all(legacy.join(LEGACY_CACHE_DIR)).unwrap();
        fs::write(legacy.join(LEGACY_CACHE_DIR).join("c.wav"), b"cached").unwrap();
        fs::write(legacy.join("speech.wav"), b"combined").unwrap();
        fs::write(legacy.join("index.html"), b"<html>").unwrap();
        fs::write(legacy.join("extracted_document.json"), b"{}").unwrap();
        let chunk = chunk_dir.join("chunk-000000.wav");
        fs::write(&chunk, b"RIFF").unwrap();
        fs::write(
            legacy.join(LEGACY_SESSION_FILE),
            serde_json::json!({
                "sourceName": "old.pdf", "sourceSha256": "ab".repeat(32),
                "narrationRulesetVersion": "r", "voice": "en_US-ryan-medium",
                "engine": "Piper", "sampleRate": 22050, "channels": 1, "sampleWidthBytes": 2,
                "chunks": [{"audioFile": chunk.to_string_lossy(), "durationSeconds": 2.0,
                            "pauseAfterMs": 0}]
            })
            .to_string(),
        )
        .unwrap();
        fs::write(
            root.join(LIBRARY_FILE),
            serde_json::json!({"version": 1, "entries": [{
                "sourceSha256": "ab".repeat(32), "sourceName": "old.pdf",
                "sourcePath": "/docs/old.pdf", "voice": "en_US-ryan-medium", "engine": "Piper",
                "chunksCount": 1, "totalDurationSeconds": 2.0, "lastListenedAt": 10
            }]})
            .to_string(),
        )
        .unwrap();
    }

    #[test]
    fn a_v1_directory_is_migrated_once_and_keeps_its_session() {
        let scratch = Scratch::new();
        let root = &scratch.0;
        seed_v1(root);

        let report = migrate_to_v2(root).unwrap();
        assert_eq!(
            report,
            MigrationReport {
                already_current: false,
                library_upgraded: true,
                cache_moved: true,
                session_kept: true,
            }
        );
        assert!(!root.join(LEGACY_OUTPUT_DIR).exists());
        assert!(audio_cache_dir(root).join("c.wav").is_file());
        assert_eq!(
            library::stored_version(&root.join(LIBRARY_FILE)),
            Some(library::LIBRARY_VERSION)
        );
        assert!(root.join("library.json.v1.bak").is_file());

        let session = load_current_session(root).expect("the 1.x session is reopened");
        let run = sessions_dir(root).join(MIGRATED_RUN_ID);
        assert_eq!(session.dir, run);
        assert!(session.chunks[0]
            .audio_file
            .starts_with(run.to_str().unwrap()));
        assert!(run.join("extracted_document.json").is_file());
        for gone in [
            "speech.wav",
            "index.html",
            LEGACY_SESSION_FILE,
            ".legacy-root",
        ] {
            assert!(!run.join(gone).exists(), "{gone} should be removed");
        }

        assert!(migrate_to_v2(root).unwrap().already_current);
    }

    #[test]
    fn an_interrupted_migration_finishes_on_the_next_launch() {
        let scratch = Scratch::new();
        let root = &scratch.0;
        seed_v1(root);
        // Simulate a crash right after the session directory was moved.
        let legacy = root.join(LEGACY_OUTPUT_DIR);
        let old_root = legacy.canonicalize().unwrap();
        let run = sessions_dir(root).join(MIGRATED_RUN_ID);
        fs::create_dir_all(sessions_dir(root)).unwrap();
        fs::rename(&legacy, &run).unwrap();
        fs::write(
            run.join(".legacy-root"),
            old_root.to_string_lossy().as_bytes(),
        )
        .unwrap();

        let report = migrate_to_v2(root).unwrap();
        assert!(report.session_kept);
        assert!(
            !report.cache_moved,
            "the cache moved with the session directory"
        );
        assert!(audio_cache_dir(root).join("c.wav").is_file());
        assert!(!run.join(LEGACY_CACHE_DIR).exists());
        assert!(load_current_session(root).is_some());
        assert!(root.join(DATA_VERSION_FILE).is_file());
    }

    #[test]
    fn a_partial_session_is_dropped_and_a_fresh_install_just_gets_a_version() {
        let scratch = Scratch::new();
        let root = &scratch.0;
        seed_v1(root);
        fs::remove_dir_all(root.join(LEGACY_OUTPUT_DIR).join("chunks")).unwrap();
        let report = migrate_to_v2(root).unwrap();
        assert!(!report.session_kept);
        assert!(load_current_session(root).is_none());
        assert!(!sessions_dir(root).join(MIGRATED_RUN_ID).exists());

        let fresh = Scratch::new();
        let report = migrate_to_v2(&fresh.0).unwrap();
        assert_eq!(report, MigrationReport::default());
        assert_eq!(
            fs::read_to_string(fresh.0.join(DATA_VERSION_FILE)).unwrap(),
            "2"
        );
    }

    #[test]
    fn newer_data_is_refused() {
        let scratch = Scratch::new();
        fs::write(scratch.0.join(DATA_VERSION_FILE), "3").unwrap();
        assert!(migrate_to_v2(&scratch.0).unwrap_err().contains("newer"));
    }
}

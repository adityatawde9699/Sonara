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
    pub(crate) sample_rate: u32,
    pub(crate) channels: u16,
    pub(crate) sample_width_bytes: u16,
    pub(crate) chunks: Vec<ReaderChunk>,
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
                .map(|chunk| FrontendChunk {
                    duration_seconds: chunk.duration_seconds,
                    pause_after_ms: chunk.pause_after_ms,
                })
                .collect(),
        }
    }
}

pub(crate) fn default_engine_name() -> String {
    "Piper".to_owned()
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Progress {
    pub(crate) version: u8,
    pub(crate) source_sha256: String,
    pub(crate) segment: usize,
    pub(crate) offset_seconds: f64,
    pub(crate) playback_rate: f64,
}

pub(crate) fn load_reader_session(
    output_dir: &Path,
    source_path: &Path,
) -> Result<ReaderSession, String> {
    let manifest_path = output_dir.join("audio_chunks.json");
    let manifest: serde_json::Value = serde_json::from_slice(
        &fs::read(&manifest_path)
            .map_err(|error| format!("Could not read the audio manifest: {error}"))?,
    )
    .map_err(|error| format!("The generated audio manifest is invalid: {error}"))?;
    let session_meta_path = output_dir.join("desktop-session.json");
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
    let sample_rate = audio_format
        .get("sample_rate")
        .and_then(serde_json::Value::as_u64)
        .and_then(|value| u32::try_from(value).ok())
        .filter(|value| *value > 0)
        .ok_or_else(|| "The manifest sample rate is invalid.".to_owned())?;
    let channels = audio_format
        .get("channels")
        .and_then(serde_json::Value::as_u64)
        .and_then(|value| u16::try_from(value).ok())
        .filter(|value| *value > 0)
        .ok_or_else(|| "The manifest channel count is invalid.".to_owned())?;
    let sample_width_bytes = audio_format
        .get("sample_width_bytes")
        .and_then(serde_json::Value::as_u64)
        .and_then(|value| u16::try_from(value).ok())
        .filter(|value| *value > 0)
        .ok_or_else(|| "The manifest sample width is invalid.".to_owned())?;
    let chunk_values = manifest
        .get("chunks")
        .and_then(serde_json::Value::as_array)
        .filter(|chunks| !chunks.is_empty())
        .ok_or_else(|| "The audio manifest contains no playable chunks.".to_owned())?;
    let canonical_output = output_dir
        .canonicalize()
        .map_err(|error| format!("Could not inspect generated audio: {error}"))?;
    let mut chunks = Vec::with_capacity(chunk_values.len());
    for (index, value) in chunk_values.iter().enumerate() {
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
        let file = output_dir.join(relative);
        let canonical_file = file
            .canonicalize()
            .map_err(|error| format!("Audio passage {} is unavailable: {error}", index + 1))?;
        if !canonical_file.starts_with(&canonical_output) || !canonical_file.is_file() {
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
        let pause_after_ms = value
            .get("pause_after_ms")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or(0);
        chunks.push(ReaderChunk {
            audio_file: canonical_file.to_string_lossy().into_owned(),
            duration_seconds,
            pause_after_ms,
        });
    }
    let session = ReaderSession {
        source_name,
        source_sha256,
        narration_ruleset_version: manifest
            .get("narration_ruleset_version")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("unknown")
            .to_owned(),
        voice: manifest
            .get("voice")
            .and_then(serde_json::Value::as_str)
            .unwrap_or(DEFAULT_FALLBACK_VOICE)
            .to_owned(),
        engine: manifest
            .get("engine")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("Piper")
            .to_owned(),
        sample_rate,
        channels,
        sample_width_bytes,
        chunks,
    };
    atomic_write_json(&session_meta_path, &session)?;
    Ok(session)
}

pub(crate) fn load_saved_session(output_dir: &Path) -> Option<ReaderSession> {
    let bytes = fs::read(output_dir.join("desktop-session.json")).ok()?;
    let mut session: ReaderSession = serde_json::from_slice(&bytes).ok()?;
    validate_hash(&session.source_sha256).ok()?;
    if session.chunks.is_empty() {
        return None;
    }
    let root = output_dir.canonicalize().ok()?;
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

/// Map an audio route to the active session's manifest entry. The session
/// lock is held only long enough to copy one path.
pub(crate) fn session_audio_lookup(
    state: &AppState,
    reader_output: Option<&Path>,
    document_hash: &str,
    index: usize,
) -> AudioLookup {
    let audio_file = {
        let Ok(session) = state.session.lock() else {
            return AudioLookup::StateError;
        };
        match session
            .as_ref()
            .filter(|session| session.source_sha256 == document_hash)
            .and_then(|session| session.chunks.get(index))
        {
            Some(chunk) => PathBuf::from(&chunk.audio_file),
            None => return AudioLookup::NotFound,
        }
    };
    match reader_output {
        Some(reader_output) => AudioLookup::Passage {
            audio_file,
            chunks_root: reader_output.join("chunks"),
        },
        None => AudioLookup::Unavailable,
    }
}

pub(crate) fn validate_progress_shape(progress: &Progress) -> Result<(), String> {
    if progress.version == 1
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn progress_requires_supported_rate_and_document_hash() {
        assert!(validate_hash(&"a".repeat(64)).is_ok());
        assert!(validate_hash("not-a-hash").is_err());
        let progress = Progress {
            version: 1,
            source_sha256: "a".repeat(64),
            segment: 0,
            offset_seconds: 2.0,
            playback_rate: 1.0,
        };
        assert!(validate_progress_shape(&progress).is_ok());
        let invalid = Progress {
            playback_rate: 2.0,
            ..progress
        };
        assert!(validate_progress_shape(&invalid).is_err());
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
            version: 1,
            source_sha256: "f".repeat(64),
            segment: 4,
            offset_seconds: 12.75,
            playback_rate: 1.2,
        };
        atomic_write_json(&path, &progress).unwrap();
        let restored: Progress = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(restored.segment, 4);
        assert_eq!(restored.offset_seconds, 12.75);
        assert_eq!(restored.playback_rate, 1.2);
        let _ = fs::remove_dir_all(root);
    }
}

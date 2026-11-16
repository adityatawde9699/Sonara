//! Installing speech models the installers do not ship (Piper voices, Kokoro).
//!
//! The download itself runs in the Python runtime (`model_downloads.py`), which
//! fetches each file over HTTPS from a fixed upstream revision and installs it
//! only after its pinned SHA-256 matches. This module starts that process,
//! relays its progress to the frontend, and lets the user cancel it.

use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader, Read};
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, Manager};

use crate::process_tree;
use crate::runtime::{configure_runtime_command, resolve_runtime, stop_worker_tree};

const SCRIPT: &str = "model_downloads.py";
pub(crate) const PROGRESS_EVENT: &str = "model-download-progress";

/// At most one download runs at a time.
#[derive(Default)]
pub(crate) struct ModelDownloads {
    active: Mutex<Option<ActiveDownload>>,
}

struct ActiveDownload {
    model: String,
    child: Arc<Mutex<Child>>,
    cancelled: Arc<AtomicBool>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ModelStatus {
    pub(crate) id: String,
    pub(crate) kind: String,
    pub(crate) label: String,
    pub(crate) size_bytes: u64,
    pub(crate) installed: bool,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DownloadProgress {
    pub(crate) model: String,
    pub(crate) received: u64,
    pub(crate) total: u64,
}

/// Model ids become a command-line argument and pick a directory; the Python
/// side checks them against its catalog, and this rejects anything odd first.
pub(crate) fn validate_model_id(model: &str) -> Result<(), String> {
    // The first character must be alphanumeric so an id is never read as an
    // option ("--dest") by the installer's argument parser.
    let valid = model.len() <= 64
        && model.starts_with(|c: char| c.is_ascii_alphanumeric())
        && model
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-');
    if valid {
        Ok(())
    } else {
        Err(format!("Unknown speech model: {model}"))
    }
}

/// One line of the installer's JSON output.
#[derive(Debug, PartialEq)]
pub(crate) enum InstallerEvent {
    Progress { received: u64, total: u64 },
    Done,
    Error(String),
}

pub(crate) fn parse_installer_line(line: &str) -> Option<InstallerEvent> {
    let value: serde_json::Value = serde_json::from_str(line.trim()).ok()?;
    match value.get("event")?.as_str()? {
        "progress" => Some(InstallerEvent::Progress {
            received: value.get("received")?.as_u64()?,
            total: value.get("total")?.as_u64()?,
        }),
        "done" => Some(InstallerEvent::Done),
        "error" => Some(InstallerEvent::Error(
            value
                .get("message")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("The model download failed.")
                .to_owned(),
        )),
        _ => None,
    }
}

fn script_path(project_root: &std::path::Path) -> Result<PathBuf, String> {
    let script = project_root.join(SCRIPT);
    if script.is_file() {
        Ok(script)
    } else {
        Err(format!(
            "The model installer is missing from this installation ({}).",
            script.display()
        ))
    }
}

pub(crate) fn model_status(app: &AppHandle) -> Result<Vec<ModelStatus>, String> {
    let runtime = resolve_runtime(Some(app))?;
    let script = script_path(&runtime.project_root)?;
    let mut command = process_tree::worker_command(&runtime.python, false);
    command
        .current_dir(&runtime.project_root)
        .arg(&script)
        .arg("status")
        .arg("--piper-dir")
        .arg(&runtime.model_dir)
        .arg("--kokoro-dir")
        .arg(&runtime.kokoro_dir)
        .stdin(Stdio::null());
    configure_runtime_command(&mut command, &runtime);
    let output = command
        .output()
        .map_err(|error| format!("Could not check the installed speech models: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "Could not check the installed speech models: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("The model installer returned an invalid status: {error}"))
}

pub(crate) fn install_model(app: &AppHandle, model: &str) -> Result<(), String> {
    validate_model_id(model)?;
    let runtime = resolve_runtime(Some(app))?;
    let script = script_path(&runtime.project_root)?;
    let destination = if model == "kokoro" {
        &runtime.kokoro_dir
    } else {
        &runtime.model_dir
    };
    let state = app.state::<ModelDownloads>();
    let mut active = state
        .active
        .lock()
        .map_err(|_| "Model download state is unavailable.".to_owned())?;
    if let Some(current) = active.as_ref() {
        return Err(format!(
            "Another model ({}) is already downloading.",
            current.model
        ));
    }

    // Network access is the point here, so proxy and CA settings pass through.
    let mut command = process_tree::worker_command(&runtime.python, true);
    command
        .current_dir(&runtime.project_root)
        .arg(&script)
        .arg("install")
        .arg(model)
        .arg("--dest")
        .arg(destination)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("PYTHONUNBUFFERED", "1");
    configure_runtime_command(&mut command, &runtime);
    #[cfg(unix)]
    command.process_group(0);
    let mut child = command
        .spawn()
        .map_err(|error| format!("Could not start the model installer: {error}"))?;
    if let Err(error) = process_tree::adopt(&child) {
        process_tree::kill_and_reap(&mut child);
        return Err(error);
    }
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    let child = Arc::new(Mutex::new(child));
    let cancelled = Arc::new(AtomicBool::new(false));
    *active = Some(ActiveDownload {
        model: model.to_owned(),
        child: Arc::clone(&child),
        cancelled: Arc::clone(&cancelled),
    });
    drop(active);

    // Drain stderr on its own thread so a chatty failure cannot block stdout.
    let stderr_reader = std::thread::spawn(move || {
        let mut text = String::new();
        if let Some(stream) = stderr {
            let _ = stream.take(16 * 1024).read_to_string(&mut text);
        }
        text
    });

    let mut outcome: Option<Result<(), String>> = None;
    if let Some(stdout) = stdout {
        for line in BufReader::new(stdout).lines() {
            let Ok(line) = line else { break };
            match parse_installer_line(&line) {
                Some(InstallerEvent::Progress { received, total }) => {
                    let _ = app.emit(
                        PROGRESS_EVENT,
                        DownloadProgress {
                            model: model.to_owned(),
                            received,
                            total,
                        },
                    );
                }
                Some(InstallerEvent::Done) => outcome = Some(Ok(())),
                Some(InstallerEvent::Error(message)) => outcome = Some(Err(message)),
                None => {}
            }
        }
    }
    let exit = child.lock().ok().and_then(|mut child| child.wait().ok());
    if let Ok(child) = child.lock() {
        process_tree::release(child.id());
    }
    let stderr_text = stderr_reader.join().unwrap_or_default();
    if let Ok(mut active) = state.active.lock() {
        *active = None;
    }

    if cancelled.load(Ordering::SeqCst) {
        remove_partial_files(destination);
        return Err("Download cancelled.".to_owned());
    }
    match outcome {
        Some(result) => result,
        None => Err(format!(
            "The model installer stopped unexpectedly{}{}",
            exit.and_then(|status| status.code())
                .map(|code| format!(" (exit code {code})"))
                .unwrap_or_default(),
            match stderr_text.trim() {
                "" => ".".to_owned(),
                detail => format!(": {}", crate::runtime::truncate_chars(detail, 400)),
            }
        )),
    }
}

/// The installer writes `.<name>.part` and renames it only once it verifies,
/// so a killed download leaves just that partial file. Remove it.
fn remove_partial_files(directory: &std::path::Path) {
    let Ok(entries) = std::fs::read_dir(directory) else {
        return;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.starts_with('.') && name.ends_with(".part") && entry.path().is_file() {
            let _ = std::fs::remove_file(entry.path());
        }
    }
}

/// Stops the running download, if any; `install_model` then removes the
/// partial file and reports the cancellation.
pub(crate) fn cancel_download(downloads: &ModelDownloads) -> bool {
    let Ok(active) = downloads.active.lock() else {
        return false;
    };
    let Some(download) = active.as_ref() else {
        return false;
    };
    download.cancelled.store(true, Ordering::SeqCst);
    if let Ok(mut child) = download.child.lock() {
        let _ = stop_worker_tree(&mut child);
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn model_ids_are_plain_names() {
        assert!(validate_model_id("kokoro").is_ok());
        assert!(validate_model_id("en_US-ryan-medium").is_ok());
        for bad in [
            "",
            "../kokoro",
            "a/b",
            "kokoro.onnx",
            "--dest",
            &"x".repeat(65),
        ] {
            assert!(validate_model_id(bad).is_err(), "{bad} should be rejected");
        }
    }

    #[test]
    fn installer_lines_are_parsed() {
        assert_eq!(
            parse_installer_line(
                r#"{"event": "progress", "model": "kokoro", "received": 5, "total": 9}"#
            ),
            Some(InstallerEvent::Progress {
                received: 5,
                total: 9
            })
        );
        assert_eq!(
            parse_installer_line(r#"{"event": "done", "model": "kokoro"}"#),
            Some(InstallerEvent::Done)
        );
        assert_eq!(
            parse_installer_line(r#"{"event": "error", "message": "SHA-256 mismatch"}"#),
            Some(InstallerEvent::Error("SHA-256 mismatch".to_owned()))
        );
        assert_eq!(parse_installer_line("not json"), None);
        assert_eq!(parse_installer_line(r#"{"event": "progress"}"#), None);
    }

    #[test]
    fn only_partial_downloads_are_removed() {
        let directory = std::env::temp_dir().join(format!("sonara-partial-{}", std::process::id()));
        std::fs::create_dir_all(&directory).unwrap();
        for name in [
            ".voice.onnx.part",
            "voice.onnx",
            "voice.onnx.json",
            "notes.part",
        ] {
            std::fs::write(directory.join(name), b"x").unwrap();
        }
        remove_partial_files(&directory);
        let mut left: Vec<String> = std::fs::read_dir(&directory)
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        left.sort();
        std::fs::remove_dir_all(&directory).unwrap();
        assert_eq!(left, ["notes.part", "voice.onnx", "voice.onnx.json"]);
    }

    #[test]
    fn cancelling_with_nothing_running_is_a_no_op() {
        assert!(!cancel_download(&ModelDownloads::default()));
    }
}

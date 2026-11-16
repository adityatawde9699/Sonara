use serde::{Deserialize, Serialize};
use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};
use std::process::Child;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter, Manager, State, WindowEvent};

mod audio_server;
mod library;
mod llm_rpc;
mod models;
mod pickers;
mod process_tree;
mod runtime;
mod session;
mod voices;

use audio_server::AudioServer;
use library::{LibraryDocument, LIBRARY_FILE};
use llm_rpc::{
    invoke_llm_rpc, llm_test_connection_inner, shutdown_llm_worker, ChatMessageInput,
    LlmChatResult, LlmConfigInput, LlmSummarizeResult, LlmTestResult, LlmWorker,
};
use pickers::{choose_document_path, choose_gguf_path};
use runtime::{
    configure_runtime_command, pdf_tool_args, resolve_runtime, spawn_sonara_worker,
    stop_worker_tree, verify_installed_runtime, worker_failure_message, WorkerOptions,
};
use session::{
    atomic_write_json, load_reader_session, load_saved_session, progress_path,
    session_audio_lookup, validate_hash, validate_progress_shape, FrontendSession, Progress,
    ReaderSession,
};
use voices::{discover_voices, VoiceInfo, DEFAULT_FALLBACK_VOICE};

const SUPPORTED_DOCUMENT_EXTENSIONS: &[&str] = &["pdf", "txt", "text", "md", "docx", "epub"];

#[derive(Default)]
struct AppState {
    selected_document: Mutex<Option<PathBuf>>,
    active: Mutex<Option<ActiveJob>>,
    session: Mutex<Option<ReaderSession>>,
    llm_worker: Mutex<Option<LlmWorker>>,
    /// A second handle to the worker process, locked only briefly. `llm_worker`
    /// is held for the whole of a request, so shutdown uses this one to kill a
    /// busy worker instead of waiting behind the in-flight call.
    llm_child: Mutex<Option<Arc<Mutex<Child>>>>,
    /// Serializes read-modify-write updates of the library file.
    library: Mutex<()>,
}

struct ActiveJob {
    id: String,
    child: Arc<Mutex<Child>>,
    cancelled: Arc<AtomicBool>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SelectedDocument {
    display_name: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct SynthesisFinished {
    job_id: String,
    result: Result<FrontendSession, String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct SynthesisProgress {
    job_id: String,
    completed_chunks: usize,
    total_chunks: usize,
}

fn library_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_local_data_dir()
        .map(|dir| dir.join(LIBRARY_FILE))
        .map_err(|error| format!("Could not find Sonara's local data directory: {error}"))
}

/// Run `action` on the library file while holding the library lock.
fn with_library<T>(
    app: &AppHandle,
    action: impl FnOnce(&Path) -> Result<T, String>,
) -> Result<T, String> {
    let path = library_path(app)?;
    let state = app.state::<AppState>();
    let _guard = state
        .library
        .lock()
        .map_err(|_| "Library state is unavailable.".to_owned())?;
    action(&path)
}

#[tauri::command]
fn list_library(app: AppHandle) -> Result<Vec<LibraryDocument>, String> {
    with_library(&app, |path| {
        Ok(library::library_documents(library::load_library(path)))
    })
}

/// Select a document from the library for narration, as the picker would.
/// The frontend names the document by hash; the path comes from the library.
#[tauri::command]
fn open_library_document(
    app: AppHandle,
    state: State<'_, AppState>,
    source_sha256: String,
) -> Result<SelectedDocument, String> {
    validate_hash(&source_sha256)?;
    let source_path = with_library(&app, |path| {
        library::find_source_path(path, &source_sha256)
            .ok_or_else(|| "This document is no longer in your library.".to_owned())
    })?;
    if !source_path.is_file() {
        return Err(
            "This document is no longer at its saved location. Open it again with Choose document."
                .to_owned(),
        );
    }
    let canonical = validate_document(&source_path)?;
    let display_name = canonical
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("Selected document")
        .to_owned();
    *state
        .selected_document
        .lock()
        .map_err(|_| "Document selection state is unavailable.".to_owned())? = Some(canonical);
    Ok(SelectedDocument { display_name })
}

#[tauri::command]
fn remove_library_document(app: AppHandle, source_sha256: String) -> Result<(), String> {
    validate_hash(&source_sha256)?;
    with_library(&app, |path| library::remove_entry(path, &source_sha256))
}

#[tauri::command]
fn clear_library(app: AppHandle) -> Result<(), String> {
    with_library(&app, library::clear_library)
}

#[tauri::command]
async fn pick_document(
    state: State<'_, AppState>,
    _app: AppHandle,
) -> Result<Option<SelectedDocument>, String> {
    let Some(path) = choose_document_path()? else {
        return Ok(None);
    };
    let canonical = validate_document(&path)?;
    let display_name = canonical
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("Selected document")
        .to_owned();
    *state
        .selected_document
        .lock()
        .map_err(|_| "Document selection state is unavailable.".to_owned())? = Some(canonical);
    Ok(Some(SelectedDocument { display_name }))
}

#[tauri::command]
async fn preview_narration(
    app: AppHandle,
    voice: Option<String>,
    expand_dates: bool,
    expand_citations: bool,
) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<AppState>();
        let selected_path = state
            .selected_document
            .lock()
            .map_err(|_| "Document selection state is unavailable.".to_owned())?
            .clone()
            .ok_or_else(|| "Choose a document before previewing narration.".to_owned())?;
        let document = validate_document(&selected_path)?;
        let runtime = resolve_runtime(Some(&app))?;
        let available_voices = discover_voices(&runtime.model_dir)?;
        let selected_voice = voice
            .filter(|candidate| available_voices.iter().any(|item| item.id == *candidate))
            .or_else(|| {
                available_voices
                    .iter()
                    .find(|item| item.is_default)
                    .map(|item| item.id.clone())
            })
            .ok_or_else(|| "No installed Piper voice is available for preview.".to_owned())?;
        let mut command = process_tree::worker_command(&runtime.python, false);
        let mut args = vec!["read", "--preview"];
        if expand_dates {
            args.push("--expand-dates");
        }
        if expand_citations {
            args.push("--expand-citations");
        }
        command
            .current_dir(&runtime.project_root)
            .arg(&runtime.script)
            .args(args)
            .arg(&document)
            .arg("--voice")
            .arg(&selected_voice)
            .arg("--data-dir")
            .arg(&runtime.model_dir)
            .args(pdf_tool_args(&runtime));
        configure_runtime_command(&mut command, &runtime);
        let output = command
            .output()
            .map_err(|error| format!("Could not preview narration: {error}"))?;
        if !output.status.success() {
            let detail = String::from_utf8_lossy(&output.stderr).trim().to_owned();
            return Err(if detail.is_empty() {
                "Could not preview narration for this document.".to_owned()
            } else {
                detail
            });
        }
        if output.stdout.len() > 2 * 1024 * 1024 {
            return Err("Narration preview exceeded its response size limit.".to_owned());
        }
        serde_json::from_slice(&output.stdout)
            .map_err(|error| format!("Narration preview returned invalid data: {error}"))
    })
    .await
    .map_err(|e| format!("Preview narration task failed: {e}"))?
}

#[tauri::command]
async fn llm_choose_model() -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        choose_gguf_path().map(|path| path.map(|value| value.to_string_lossy().into_owned()))
    })
    .await
    .map_err(|e| format!("Choose model task failed: {e}"))?
}

#[tauri::command]
fn current_session(
    state: State<'_, AppState>,
    audio_server: State<'_, AudioServer>,
) -> Result<Option<FrontendSession>, String> {
    Ok(state
        .session
        .lock()
        .map_err(|_| "Reader session state is unavailable.".to_owned())?
        .as_ref()
        .map(|session| FrontendSession::from_session(session, &audio_server.base_url)))
}

/// Speech models the app can download, and whether each is installed.
#[tauri::command]
async fn list_models(app: AppHandle) -> Result<Vec<models::ModelStatus>, String> {
    tauri::async_runtime::spawn_blocking(move || models::model_status(&app))
        .await
        .map_err(|error| format!("Model status task failed: {error}"))?
}

/// Downloads and verifies one model; progress arrives as
/// `model-download-progress` events. Resolves when it is installed.
#[tauri::command]
async fn install_model(app: AppHandle, model: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || models::install_model(&app, &model))
        .await
        .map_err(|error| format!("Model download task failed: {error}"))?
}

#[tauri::command]
fn cancel_model_download(downloads: State<'_, models::ModelDownloads>) -> bool {
    models::cancel_download(downloads.inner())
}

#[tauri::command]
fn list_kokoro_voices() -> Vec<VoiceInfo> {
    voices::kokoro_voices()
}

/// The open session's document as blocks, for read-along highlighting.
#[tauri::command]
async fn get_reader_document(app: AppHandle) -> Result<session::ReaderDocument, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<AppState>();
        let sha256 = state
            .session
            .lock()
            .map_err(|_| "Reader session state is unavailable.".to_owned())?
            .as_ref()
            .map(|session| session.source_sha256.clone())
            .ok_or_else(|| "No document is open.".to_owned())?;
        let output_dir = app
            .path()
            .app_local_data_dir()
            .map_err(|error| format!("Could not get app data dir: {error}"))?
            .join("reader-output");
        session::load_reader_document(&output_dir, &sha256)
    })
    .await
    .map_err(|error| format!("Reader document task failed: {error}"))?
}

#[tauri::command]
fn list_voices(app: AppHandle) -> Result<Vec<VoiceInfo>, String> {
    let runtime = resolve_runtime(Some(&app))?;
    if !runtime.model_dir.is_dir() {
        return Ok(Vec::new());
    }
    discover_voices(&runtime.model_dir)
}

// Each parameter is a top-level key in the frontend's `invoke` payload, so
// grouping them into a struct would change the IPC contract.
#[allow(clippy::too_many_arguments)]
#[tauri::command]
fn start_reading(
    app: AppHandle,
    state: State<'_, AppState>,
    voice: Option<String>,
    variation: Option<String>,
    expand_dates: Option<bool>,
    expand_citations: Option<bool>,
    engine: Option<String>,
    resource_profile: Option<String>,
) -> Result<String, String> {
    let selected_path = state
        .selected_document
        .lock()
        .map_err(|_| "Document selection state is unavailable.".to_owned())?
        .clone()
        .ok_or_else(|| "Choose a supported document before starting narration.".to_owned())?;
    let document = validate_document(&selected_path)?;

    let mut active = state
        .active
        .lock()
        .map_err(|_| "Synthesis state is unavailable.".to_owned())?;
    if active.is_some() {
        return Err(
            "A document is already being synthesized. Cancel it before starting another."
                .to_owned(),
        );
    }

    let runtime = resolve_runtime(Some(&app))?;
    let selected_engine = engine.unwrap_or_else(|| "piper".to_owned());
    if !["piper", "kokoro"].contains(&selected_engine.as_str()) {
        return Err("Choose Piper or Kokoro as the speech engine.".to_owned());
    }
    let selected_profile = resource_profile.unwrap_or_else(|| "standard".to_owned());
    if !["low_resource", "standard", "high_performance"].contains(&selected_profile.as_str()) {
        return Err("Choose a valid resource profile.".to_owned());
    }
    let selected_voice = match voice.as_deref() {
        Some(v) if !v.trim().is_empty() => {
            let candidate = v.trim();
            if !candidate
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
            {
                return Err("Invalid voice name.".to_owned());
            }
            if selected_engine == "piper"
                && (!runtime
                    .model_dir
                    .join(format!("{candidate}.onnx"))
                    .is_file()
                    || !runtime
                        .model_dir
                        .join(format!("{candidate}.onnx.json"))
                        .is_file())
            {
                return Err(format!(
                    "Selected voice '{candidate}' is not installed in {}.",
                    runtime.model_dir.display()
                ));
            }
            if selected_engine == "kokoro" && !voices::is_kokoro_voice(candidate) {
                return Err("Choose one of the Kokoro voices listed in Settings.".to_owned());
            }
            candidate.to_string()
        }
        _ => {
            if selected_engine == "kokoro" {
                voices::DEFAULT_KOKORO_VOICE.to_owned()
            } else {
                let voices = discover_voices(&runtime.model_dir)?;
                voices
                    .iter()
                    .find(|v| v.is_default)
                    .map(|v| v.id.clone())
                    .unwrap_or_else(|| DEFAULT_FALLBACK_VOICE.to_string())
            }
        }
    };
    let selected_variation = variation.unwrap_or_else(|| "voice_default".to_owned());
    if !["voice_default", "less", "more"].contains(&selected_variation.as_str()) {
        return Err("Choose a valid Piper variation setting.".to_owned());
    }

    let app_data = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("Could not find Sonara's local data directory: {error}"))?;
    let output_dir = app_data.join("reader-output");
    fs::create_dir_all(&output_dir)
        .map_err(|error| format!("Could not create Sonara's local audio directory: {error}"))?;
    let log_path = app_data.join("worker.log");
    let log = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(&log_path)
        .map_err(|error| format!("Could not prepare the local worker log: {error}"))?;
    let error_log = log
        .try_clone()
        .map_err(|error| format!("Could not prepare the local worker log: {error}"))?;

    let options = WorkerOptions {
        voice: &selected_voice,
        variation: &selected_variation,
        engine: &selected_engine,
        resource_profile: &selected_profile,
        expand_dates: expand_dates.unwrap_or(false),
        expand_citations: expand_citations.unwrap_or(false),
    };
    let child = spawn_sonara_worker(&runtime, &document, &output_dir, &options, log, error_log)
        .map_err(|error| format!("Could not start the Sonara Python worker: {error}"))?;
    let job_id = make_job_id();
    let child = Arc::new(Mutex::new(child));
    let cancelled = Arc::new(AtomicBool::new(false));
    *active = Some(ActiveJob {
        id: job_id.clone(),
        child: Arc::clone(&child),
        cancelled: Arc::clone(&cancelled),
    });
    drop(active);

    let monitor_app = app.clone();
    let monitor_id = job_id.clone();
    thread::Builder::new()
        .name("sonara-python-worker-monitor".to_owned())
        .spawn(move || {
            monitor_worker(
                monitor_app,
                monitor_id,
                child,
                cancelled,
                document,
                output_dir,
                log_path,
            )
        })
        .map_err(|error| {
            terminate_active(&app, &job_id);
            format!("Could not monitor the speech worker: {error}")
        })?;
    Ok(job_id)
}

#[tauri::command]
fn cancel_reading(state: State<'_, AppState>) -> Result<bool, String> {
    let active = state
        .active
        .lock()
        .map_err(|_| "Synthesis state is unavailable.".to_owned())?;
    let Some(job) = active.as_ref() else {
        return Ok(false);
    };
    job.cancelled.store(true, Ordering::SeqCst);
    let mut child = job
        .child
        .lock()
        .map_err(|_| "Speech worker state is unavailable.".to_owned())?;
    stop_worker_tree(&mut child)?;
    Ok(true)
}

#[tauri::command]
fn load_progress(app: AppHandle, source_sha256: String) -> Result<Option<Progress>, String> {
    validate_hash(&source_sha256)?;
    let path = progress_path(&app, &source_sha256)?;
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(format!("Could not read saved progress: {error}")),
    };
    let progress: Progress = serde_json::from_slice(&bytes)
        .map_err(|_| "Saved reading progress is invalid and was not restored.".to_owned())?;
    if progress.version != 1
        || progress.source_sha256 != source_sha256
        || !progress.offset_seconds.is_finite()
        || progress.offset_seconds < 0.0
        || !progress.playback_rate.is_finite()
        || !(0.7..=1.5).contains(&progress.playback_rate)
    {
        return Err("Saved reading progress contains unsupported values.".to_owned());
    }
    Ok(Some(progress))
}

#[tauri::command]
fn save_progress(
    app: AppHandle,
    state: State<'_, AppState>,
    progress: Progress,
) -> Result<(), String> {
    validate_hash(&progress.source_sha256)?;
    validate_progress_shape(&progress)?;
    let session = state
        .session
        .lock()
        .map_err(|_| "Reader session state is unavailable.".to_owned())?
        .clone()
        .ok_or_else(|| "There is no open reading session.".to_owned())?;
    let Some(chunk) = session.chunks.get(progress.segment) else {
        return Err("The saved passage is outside this document.".to_owned());
    };
    if session.source_sha256 != progress.source_sha256
        || progress.offset_seconds > chunk.duration_seconds + 0.1
    {
        return Err("Reading progress does not match the open document.".to_owned());
    }
    let path = progress_path(&app, &progress.source_sha256)?;
    atomic_write_json(&path, &progress)
}

#[tauri::command]
async fn llm_test_connection(
    app: AppHandle,
    config: LlmConfigInput,
) -> Result<LlmTestResult, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<AppState>();
        llm_test_connection_inner(Some(&app), &state, config)
    })
    .await
    .map_err(|e| format!("LLM test connection task failed: {e}"))?
}

#[tauri::command]
async fn llm_chat(
    app: AppHandle,
    config: LlmConfigInput,
    question: String,
    context: Option<String>,
    history: Option<Vec<ChatMessageInput>>,
) -> Result<LlmChatResult, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<AppState>();
        let req = serde_json::json!({
            "action": "chat",
            "config": config,
            "question": question,
            "context": context.unwrap_or_default(),
            "history": history.unwrap_or_default(),
        });
        let val = invoke_llm_rpc(Some(&app), &state, &req)?;
        let result: LlmChatResult = serde_json::from_value(val)
            .map_err(|e| format!("Failed to decode LLM chat response: {e}"))?;
        Ok(result)
    })
    .await
    .map_err(|e| format!("LLM chat task failed: {e}"))?
}

#[tauri::command]
async fn llm_summarize(
    app: AppHandle,
    config: LlmConfigInput,
    text: String,
    mode: Option<String>,
) -> Result<LlmSummarizeResult, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<AppState>();
        let req = serde_json::json!({
            "action": "summarize",
            "config": config,
            "text": text,
            "mode": mode.unwrap_or_else(|| "summary".to_string()),
        });
        let val = invoke_llm_rpc(Some(&app), &state, &req)?;
        let result: LlmSummarizeResult = serde_json::from_value(val)
            .map_err(|e| format!("Failed to decode LLM summarize response: {e}"))?;
        Ok(result)
    })
    .await
    .map_err(|e| format!("LLM summarize task failed: {e}"))?
}

#[tauri::command]
async fn llm_model_status(
    app: AppHandle,
    config: LlmConfigInput,
) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<AppState>();
        let req = serde_json::json!({"action": "model_status", "config": config});
        invoke_llm_rpc(Some(&app), &state, &req)
    })
    .await
    .map_err(|e| format!("LLM model status task failed: {e}"))?
}

#[tauri::command]
async fn llm_discover_models(
    app: AppHandle,
    config: LlmConfigInput,
) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<AppState>();
        let req = serde_json::json!({"action": "discover_models", "config": config});
        invoke_llm_rpc(Some(&app), &state, &req)
    })
    .await
    .map_err(|e| format!("LLM discover models task failed: {e}"))?
}

#[tauri::command]
async fn get_document_text(app: AppHandle) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<AppState>();
        // The target is derived only from backend state; the frontend cannot
        // choose which file is read.
        let target = {
            let reader_dir = app
                .path()
                .app_local_data_dir()
                .map_err(|e| format!("Could not get app data dir: {e}"))?
                .join("reader-output");
            let txt_file = reader_dir.join("document_text.txt");
            if txt_file.is_file() {
                reader_dir.to_string_lossy().into_owned()
            } else if let Ok(guard) = state.selected_document.lock() {
                if let Some(selected) = guard.as_ref() {
                    selected.to_string_lossy().into_owned()
                } else {
                    return Err("No document is currently loaded or selected.".to_owned());
                }
            } else {
                return Err("Document state unavailable.".to_owned());
            }
        };

        let req = serde_json::json!({
            "action": "get_document_text",
            "path": target,
        });
        let val = invoke_llm_rpc(Some(&app), &state, &req)?;
        if val.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
            let text = val
                .get("text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            Ok(text)
        } else {
            let err = val
                .get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("Unknown error retrieving document text");
            Err(err.to_string())
        }
    })
    .await
    .map_err(|e| format!("Get document text task failed: {e}"))?
}

fn monitor_worker(
    app: AppHandle,
    job_id: String,
    child: Arc<Mutex<Child>>,
    cancelled: Arc<AtomicBool>,
    document_path: PathBuf,
    output_dir: PathBuf,
    log_path: PathBuf,
) {
    let mut last_reported_chunks = 0;
    let chunks_manifest_path = output_dir.join("audio_chunks.json");

    let exit_status = loop {
        if let Ok(content) = fs::read_to_string(&chunks_manifest_path) {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&content) {
                let completed = val
                    .get("completed_units")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0) as usize;
                let total = val.get("total_units").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                if completed > last_reported_chunks {
                    last_reported_chunks = completed;
                    let _ = app.emit(
                        "synthesis-progress",
                        SynthesisProgress {
                            job_id: job_id.clone(),
                            completed_chunks: completed,
                            total_chunks: total,
                        },
                    );
                }
            }
        }

        let status = match child.lock() {
            Ok(mut child) => child.try_wait(),
            Err(_) => break Err("Speech worker state was poisoned.".to_owned()),
        };
        match status {
            Ok(Some(status)) => break Ok(status),
            Ok(None) => thread::sleep(Duration::from_millis(150)),
            Err(error) => break Err(format!("Could not monitor speech worker: {error}")),
        }
    };

    // The worker has exited; close its job so nothing it started survives.
    if let Ok(child) = child.lock() {
        process_tree::release(child.id());
    }

    let session_result = match exit_status {
        Err(error) => Err(error),
        Ok(_) if cancelled.load(Ordering::SeqCst) => {
            Err("Speech generation was cancelled.".to_owned())
        }
        Ok(status) if !status.success() => Err(worker_failure_message(&log_path, status.code())),
        Ok(_) => load_reader_session(&output_dir, &document_path),
    };

    if let Ok(state) = app.state::<AppState>().inner().active.lock() {
        if state.as_ref().is_some_and(|job| job.id == job_id) {
            drop(state);
            if let Ok(mut state) = app.state::<AppState>().inner().active.lock() {
                *state = None;
            }
        }
    }
    if let Ok(session) = &session_result {
        if let Ok(mut current) = app.state::<AppState>().inner().session.lock() {
            *current = Some(session.clone());
        }
        // The audio is ready either way; a library that cannot be written
        // only means this document will not be offered for reopening.
        let _ = with_library(&app, |path| {
            library::record_session(path, session, &document_path, library::now_millis())
        });
    }
    let audio_base_url = app.state::<AudioServer>().base_url.clone();
    let result =
        session_result.map(|session| FrontendSession::from_session(&session, &audio_base_url));
    let _ = app.emit("synthesis-finished", SynthesisFinished { job_id, result });
}

fn validate_document(path: &Path) -> Result<PathBuf, String> {
    let canonical = path
        .canonicalize()
        .map_err(|error| format!("Could not open the selected document: {error}"))?;
    if !canonical.is_file() {
        return Err("Choose a readable document.".to_owned());
    }
    let is_supported = canonical
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| {
            SUPPORTED_DOCUMENT_EXTENSIONS
                .iter()
                .any(|supported| extension.eq_ignore_ascii_case(supported))
        });
    if !is_supported {
        return Err("Choose a readable PDF, text, Markdown, DOCX, or EPUB document (.pdf, .txt, .text, .md, .docx, .epub).".to_owned());
    }
    Ok(canonical)
}

fn make_job_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_nanos());
    format!("{}-{nanos}", std::process::id())
}

fn terminate_active(app: &AppHandle, job_id: &str) {
    if let Ok(mut active) = app.state::<AppState>().inner().active.lock() {
        if active.as_ref().is_some_and(|job| job.id == job_id) {
            if let Some(job) = active.take() {
                job.cancelled.store(true, Ordering::SeqCst);
                if let Ok(mut child) = job.child.lock() {
                    let _ = stop_worker_tree(&mut child);
                }
            }
        }
    }
}

pub fn run() {
    tauri::Builder::default()
        .manage(AppState::default())
        .manage(models::ModelDownloads::default())
        .invoke_handler(tauri::generate_handler![
            pick_document,
            preview_narration,
            current_session,
            start_reading,
            cancel_reading,
            load_progress,
            save_progress,
            list_voices,
            list_kokoro_voices,
            list_models,
            install_model,
            cancel_model_download,
            get_reader_document,
            llm_test_connection,
            llm_chat,
            llm_summarize,
            llm_model_status,
            llm_discover_models,
            llm_choose_model,
            get_document_text,
            list_library,
            open_library_document,
            remove_library_document,
            clear_library
        ])
        .setup(|app| {
            if std::env::args().any(|argument| argument == "--sonara-smoke-check") {
                verify_installed_runtime(app.handle()).map_err(std::io::Error::other)?;
                app.handle().exit(0);
                return Ok(());
            }
            let lookup_app = app.handle().clone();
            let audio_server = AudioServer::start(Arc::new(move |hash: &str, index: usize| {
                let reader_output = lookup_app
                    .path()
                    .app_local_data_dir()
                    .ok()
                    .map(|path| path.join("reader-output"));
                session_audio_lookup(
                    lookup_app.state::<AppState>().inner(),
                    reader_output.as_deref(),
                    hash,
                    index,
                )
            }))?;
            app.manage(audio_server);
            let output_dir = app.path().app_local_data_dir()?.join("reader-output");
            if let Some(session) = load_saved_session(&output_dir) {
                *app.state::<AppState>()
                    .session
                    .lock()
                    .map_err(|_| std::io::Error::other("session state unavailable"))? =
                    Some(session);
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                let app = window.app_handle();
                app.state::<AudioServer>().stop();
                shutdown_llm_worker(app.state::<AppState>().inner());
                models::cancel_download(app.state::<models::ModelDownloads>().inner());
                if let Ok(mut active) = app.state::<AppState>().active.lock() {
                    if let Some(job) = active.take() {
                        job.cancelled.store(true, Ordering::SeqCst);
                        if let Ok(mut child) = job.child.lock() {
                            let _ = stop_worker_tree(&mut child);
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("Sonara desktop application failed to start");
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn document_selection_accepts_supported_and_rejects_other_files() {
        let unsupported = std::env::temp_dir().join(format!("{}.bin", make_job_id()));
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&unsupported)
            .unwrap()
            .write_all(b"binary payload")
            .unwrap();
        assert!(validate_document(&unsupported).is_err());
        let _ = fs::remove_file(unsupported);

        for ext in SUPPORTED_DOCUMENT_EXTENSIONS
            .iter()
            .copied()
            .chain(["PDF", "MD"])
        {
            let supported = std::env::temp_dir().join(format!("{}.{}", make_job_id(), ext));
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&supported)
                .unwrap()
                .write_all(b"document payload")
                .unwrap();
            assert!(validate_document(&supported).is_ok());
            let _ = fs::remove_file(supported);
        }
    }
}

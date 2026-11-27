//! The persistent Python LLM worker and its line-delimited JSON RPC.

use crate::process_tree;
use crate::runtime::{configure_runtime_command, resolve_runtime};
use crate::AppState;
use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader, Read, Write};
use std::process::{Child, Stdio};
use std::sync::atomic::Ordering;
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::{AppHandle, Manager};

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LlmConfigInput {
    pub provider: String,
    pub endpoint: Option<String>,
    pub model: Option<String>,
    pub api_key: Option<String>,
    pub temperature: Option<f64>,
    pub max_tokens: Option<u32>,
    pub embedding_model: Option<String>,
    pub embedding_endpoint: Option<String>,
    pub model_path: Option<String>,
    pub model_directory: Option<String>,
    pub context_size: Option<u32>,
    pub threads: Option<u32>,
    pub batch_size: Option<u32>,
    pub idle_timeout_seconds: Option<u32>,
    /// llama.cpp provider: use the server Sonara supervises (llm_server.rs).
    /// Rust then fills in the endpoints; the worker never sees this flag.
    #[serde(default, skip_serializing)]
    pub managed_server: Option<bool>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ChatMessageInput {
    pub role: String,
    pub content: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LlmTestResult {
    pub ok: bool,
    pub provider: Option<String>,
    pub model: Option<String>,
    pub latency_ms: Option<u64>,
    pub response: Option<String>,
    pub error: Option<String>,
    pub model_state: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LlmChatResult {
    pub ok: bool,
    pub answer: Option<String>,
    pub error: Option<String>,
    /// Passages the answer cites, among those it was given.
    #[serde(default)]
    pub citations: Vec<Citation>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Citation {
    /// The label as written in the answer, such as "Passage 3".
    pub label: String,
    pub passage_index: u32,
    pub page: Option<u32>,
    /// "page" or "section"; see `session::page_label_for`.
    pub page_label: String,
    pub spans: Vec<CitationSpan>,
    pub excerpt: String,
}

/// Code-point offsets `[start, end)` in a document block.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CitationSpan {
    pub block_id: String,
    pub start: u32,
    pub end: u32,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LlmSummarizeResult {
    pub ok: bool,
    pub summary: Option<String>,
    pub error: Option<String>,
}

/// Longest wait for one LLM worker reply. Embedded CPU inference on a large
/// model can be slow; HTTP providers time out after 60 s inside the worker.
pub(crate) const LLM_RPC_TIMEOUT: Duration = Duration::from_secs(300);

pub(crate) const LLM_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(3);

/// The error of a request stopped with `llm_cancel`. The frontend matches it.
pub(crate) const LLM_CANCELLED: &str = "The request was stopped.";

pub(crate) const MAX_LLM_RESPONSE_BYTES: u64 = 16 * 1024 * 1024;

pub(crate) enum LlmLine {
    Line(Vec<u8>),
    TooLarge,
    ReadError(String),
}

pub(crate) struct LlmWorker {
    pub(crate) child: Arc<Mutex<Child>>,
    #[cfg_attr(not(test), allow(dead_code))]
    pub(crate) pid: u32,
    pub(crate) stdin: std::process::ChildStdin,
    /// Lines read from the worker's stdout by a dedicated thread, so requests
    /// can wait with a timeout instead of blocking forever.
    pub(crate) lines: Receiver<LlmLine>,
}

impl LlmWorker {
    pub(crate) fn kill(&self) {
        if let Ok(mut child) = self.child.lock() {
            process_tree::kill_and_reap(&mut child);
        }
    }
}

pub(crate) fn spawn_llm_line_reader(stdout: std::process::ChildStdout) -> Receiver<LlmLine> {
    let (sender, receiver) = mpsc::channel();
    let spawned = thread::Builder::new()
        .name("sonara-llm-stdout".to_owned())
        .spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut line = Vec::new();
                let message = match (&mut reader)
                    .take(MAX_LLM_RESPONSE_BYTES + 1)
                    .read_until(b'\n', &mut line)
                {
                    Ok(0) => break, // EOF: dropping the sender signals the exit.
                    Ok(read) if read as u64 > MAX_LLM_RESPONSE_BYTES => LlmLine::TooLarge,
                    Ok(_) => LlmLine::Line(line),
                    Err(error) => LlmLine::ReadError(error.to_string()),
                };
                let stop = !matches!(message, LlmLine::Line(_));
                if sender.send(message).is_err() || stop {
                    break;
                }
            }
        });
    if spawned.is_err() {
        // Without a reader every request reports a disconnected worker.
        let (_, receiver) = mpsc::channel();
        return receiver;
    }
    receiver
}

pub(crate) fn invoke_llm_rpc(
    app: Option<&AppHandle>,
    state: &AppState,
    request: &serde_json::Value,
) -> Result<serde_json::Value, String> {
    let runtime = resolve_runtime(app)?;
    let llm_script = runtime.llm_script.clone();
    if !llm_script.is_file() {
        return Err("LLM client script (llm_client.py) was not found in project root.".to_owned());
    }
    let mut worker_guard = state
        .llm_worker
        .lock()
        .map_err(|_| "LLM worker state is unavailable.".to_owned())?;
    let exited = worker_guard.as_ref().is_some_and(|worker| {
        worker
            .child
            .lock()
            .map(|mut child| child.try_wait().ok().flatten().is_some())
            .unwrap_or(true)
    });
    if exited {
        *worker_guard = None;
    }
    // Only a cancel during this request counts.
    state.llm_cancel_requested.store(false, Ordering::SeqCst);
    if worker_guard.is_none() {
        // The worker may call an HTTP provider, so proxy and CA settings pass.
        let mut command = process_tree::worker_command(&runtime.python, true);
        command
            .arg(&llm_script)
            .arg("worker")
            .current_dir(&runtime.project_root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        configure_runtime_command(&mut command, &runtime);
        // Keep the assistant's embedding cache with the rest of Sonara's
        // data (storage::EMBEDDING_CACHE_DIR), where Settings can clear it.
        // A SONARA_CACHE_DIR the user set still wins.
        let app_data = app
            .filter(|_| std::env::var_os("SONARA_CACHE_DIR").is_none())
            .and_then(|app| app.path().app_local_data_dir().ok());
        if let Some(app_data) = app_data {
            command.env("SONARA_CACHE_DIR", app_data);
        }
        let mut child = command
            .spawn()
            .map_err(|error| format!("Failed to start Sonara's local LLM worker: {error}"))?;
        if let Err(error) = process_tree::adopt(&child) {
            process_tree::kill_and_reap(&mut child);
            return Err(error);
        }
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| "LLM worker stdin was unavailable.".to_owned())?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "LLM worker stdout was unavailable.".to_owned())?;
        let pid = child.id();
        let child = Arc::new(Mutex::new(child));
        if let Ok(mut handle) = state.llm_child.lock() {
            *handle = Some(Arc::clone(&child));
        }
        *worker_guard = Some(LlmWorker {
            child,
            pid,
            stdin,
            lines: spawn_llm_line_reader(stdout),
        });
    }
    let Some(worker) = worker_guard.as_mut() else {
        return Err("Sonara's local LLM worker could not be started.".to_owned());
    };
    let mut request_line = serde_json::to_vec(request)
        .map_err(|error| format!("Failed to serialize LLM request: {error}"))?;
    if request_line.len() > 4 * 1024 * 1024 {
        return Err("LLM request exceeded the 4 MiB limit.".to_owned());
    }
    request_line.push(b'\n');
    if let Err(error) = worker
        .stdin
        .write_all(&request_line)
        .and_then(|_| worker.stdin.flush())
    {
        discard_llm_worker(state, &mut worker_guard);
        return Err(format!(
            "Could not send request to Sonara's local LLM worker: {error}"
        ));
    }

    let reply = worker.lines.recv_timeout(LLM_RPC_TIMEOUT);
    let failure = match reply {
        Ok(LlmLine::Line(line)) => match serde_json::from_slice(&line) {
            Ok(result) => return Ok(result),
            Err(error) => format!("Sonara's local LLM worker returned invalid JSON: {error}"),
        },
        Ok(LlmLine::TooLarge) => "LLM response exceeded the 16 MiB limit.".to_owned(),
        Ok(LlmLine::ReadError(error)) => {
            format!("Could not read response from Sonara's local LLM worker: {error}")
        }
        Err(RecvTimeoutError::Timeout) => format!(
            "Sonara's local LLM worker did not answer within {} seconds and was stopped.",
            LLM_RPC_TIMEOUT.as_secs()
        ),
        Err(RecvTimeoutError::Disconnected) => {
            "Sonara's local LLM worker exited without a response.".to_owned()
        }
    };
    // Any failure leaves the stream out of step with requests, so the worker
    // is replaced rather than reused; a late reply can never answer the next call.
    discard_llm_worker(state, &mut worker_guard);
    if state.llm_cancel_requested.swap(false, Ordering::SeqCst) {
        return Err(LLM_CANCELLED.to_owned());
    }
    Err(failure)
}

/// Stop the request in flight by killing its worker through the side
/// handle, as shutdown does; the waiting call then sees the worker exit.
/// Returns false when no request holds the worker.
pub(crate) fn cancel_llm_request(state: &AppState) -> bool {
    if state.llm_worker.try_lock().is_ok() {
        return false;
    }
    state.llm_cancel_requested.store(true, Ordering::SeqCst);
    let child = state
        .llm_child
        .lock()
        .ok()
        .and_then(|mut handle| handle.take());
    if let Some(child) = child {
        if let Ok(mut child) = child.lock() {
            process_tree::kill_and_reap(&mut child);
        }
    }
    true
}

pub(crate) fn discard_llm_worker(state: &AppState, worker_guard: &mut Option<LlmWorker>) {
    if let Some(worker) = worker_guard.take() {
        worker.kill();
    }
    if let Ok(mut handle) = state.llm_child.lock() {
        *handle = None;
    }
}

pub(crate) fn llm_test_connection_inner(
    app: Option<&AppHandle>,
    state: &AppState,
    config: LlmConfigInput,
) -> Result<LlmTestResult, String> {
    let req = serde_json::json!({
        "action": "test_connection",
        "config": config,
    });
    let val = invoke_llm_rpc(app, state, &req)?;
    let result: LlmTestResult = serde_json::from_value(val)
        .map_err(|e| format!("Failed to decode LLM test connection response: {e}"))?;
    Ok(result)
}

pub(crate) fn shutdown_llm_worker(state: &AppState) {
    // If a request is in flight the worker lock is held for its whole
    // duration; kill the process through the side handle so closing the app
    // never waits on a slow model. The in-flight call then sees the worker exit.
    let mut guard = match state.llm_worker.try_lock() {
        Ok(guard) => guard,
        Err(_) => {
            if let Ok(mut handle) = state.llm_child.lock() {
                if let Some(child) = handle.take() {
                    if let Ok(mut child) = child.lock() {
                        process_tree::kill_and_reap(&mut child);
                    }
                }
            }
            return;
        }
    };
    let Some(mut worker) = guard.take() else {
        return;
    };
    if let Ok(mut handle) = state.llm_child.lock() {
        *handle = None;
    }
    let shutdown = b"{\"action\":\"shutdown\",\"config\":{\"provider\":\"embedded_llama_cpp\"}}\n";
    let _ = worker.stdin.write_all(shutdown);
    let _ = worker.stdin.flush();
    // Give the worker a moment to unload its model, then stop it regardless.
    let _ = worker.lines.recv_timeout(LLM_SHUTDOWN_TIMEOUT);
    worker.kill();
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::Command;

    #[test]
    fn llm_rpc_test_connection_offline_returns_error() {
        let config = LlmConfigInput {
            provider: "ollama".to_string(),
            endpoint: Some("http://127.0.0.1:59998/v1".to_string()),
            model: Some("llama3.2".to_string()),
            api_key: None,
            temperature: Some(0.7),
            max_tokens: Some(100),
            embedding_model: None,
            embedding_endpoint: None,
            model_path: None,
            model_directory: None,
            context_size: None,
            threads: None,
            batch_size: None,
            idle_timeout_seconds: None,
            managed_server: None,
        };
        let state = AppState::default();
        let result = llm_test_connection_inner(None, &state, config)
            .expect("IPC invocation should return a structured result");
        shutdown_llm_worker(&state);
        assert!(!result.ok);
        assert!(result.error.is_some());
    }

    #[cfg(unix)]
    #[test]
    fn llm_line_reader_reports_lines_then_disconnects_at_eof() {
        let mut child = Command::new("echo")
            .arg(r#"{"ok":true}"#)
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let lines = spawn_llm_line_reader(child.stdout.take().unwrap());
        match lines.recv_timeout(Duration::from_secs(5)) {
            Ok(LlmLine::Line(line)) => assert_eq!(line, b"{\"ok\":true}\n"),
            _ => panic!("expected one response line"),
        }
        assert!(matches!(
            lines.recv_timeout(Duration::from_secs(5)),
            Err(RecvTimeoutError::Disconnected)
        ));
        let _ = child.wait();
    }

    #[cfg(unix)]
    #[test]
    fn shutdown_kills_a_busy_llm_worker_without_waiting_for_its_reply() {
        let state = Arc::new(AppState::default());
        let mut child = Command::new("sleep")
            .arg("60")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let stdin = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();
        let pid = child.id();
        let child = Arc::new(Mutex::new(child));
        *state.llm_child.lock().unwrap() = Some(Arc::clone(&child));
        *state.llm_worker.lock().unwrap() = Some(LlmWorker {
            child: Arc::clone(&child),
            pid,
            stdin,
            lines: spawn_llm_line_reader(stdout),
        });

        // Simulate an in-flight request: hold the worker lock, as invoke_llm_rpc does.
        let (held, release) = (Arc::new(std::sync::Barrier::new(2)), Arc::clone(&state));
        let held_clone = Arc::clone(&held);
        let busy = thread::spawn(move || {
            let guard = release.llm_worker.lock().unwrap();
            held_clone.wait();
            thread::sleep(Duration::from_millis(500));
            drop(guard);
        });
        held.wait();

        let started = std::time::Instant::now();
        shutdown_llm_worker(&state);
        assert!(
            started.elapsed() < Duration::from_secs(5),
            "shutdown must not wait for the request"
        );
        let status = child.lock().unwrap().try_wait().unwrap();
        assert!(status.is_some(), "busy worker should have been killed");
        busy.join().unwrap();
    }

    #[test]
    fn cancel_stops_only_a_request_in_flight() {
        let state = Arc::new(AppState::default());
        assert!(!cancel_llm_request(&state), "nothing is running");

        let mut child = Command::new("sleep")
            .arg("60")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let stdin = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();
        let pid = child.id();
        let child = Arc::new(Mutex::new(child));
        *state.llm_child.lock().unwrap() = Some(Arc::clone(&child));
        *state.llm_worker.lock().unwrap() = Some(LlmWorker {
            child: Arc::clone(&child),
            pid,
            stdin,
            lines: spawn_llm_line_reader(stdout),
        });

        // An in-flight request holds the worker lock and waits for a line.
        let (held, waiting) = (Arc::new(std::sync::Barrier::new(2)), Arc::clone(&state));
        let held_clone = Arc::clone(&held);
        let request = thread::spawn(move || {
            let mut guard = waiting.llm_worker.lock().unwrap();
            held_clone.wait();
            let reply = guard
                .as_ref()
                .unwrap()
                .lines
                .recv_timeout(Duration::from_secs(10));
            assert!(matches!(reply, Err(RecvTimeoutError::Disconnected)));
            discard_llm_worker(&waiting, &mut guard);
            waiting.llm_cancel_requested.swap(false, Ordering::SeqCst)
        });
        held.wait();

        assert!(cancel_llm_request(&state));
        assert!(request.join().unwrap(), "the request sees it was cancelled");
        assert!(child.lock().unwrap().try_wait().unwrap().is_some());
        assert!(state.llm_worker.lock().unwrap().is_none());
    }

    #[test]
    fn embedded_llm_worker_is_reused_without_startup_model_load() {
        let state = AppState::default();
        let request = serde_json::json!({
            "action": "model_status",
            "config": {"provider": "embedded_llama_cpp"}
        });
        let first = invoke_llm_rpc(None, &state, &request).expect("status request should complete");
        assert_eq!(first["state"], "UNLOADED");
        let first_pid = state.llm_worker.lock().unwrap().as_ref().unwrap().pid;

        let second =
            invoke_llm_rpc(None, &state, &request).expect("second status request should complete");
        let second_pid = state.llm_worker.lock().unwrap().as_ref().unwrap().pid;
        assert_eq!(second["state"], "UNLOADED");
        assert_eq!(first_pid, second_pid);
        shutdown_llm_worker(&state);
    }
}

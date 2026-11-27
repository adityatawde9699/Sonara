//! A llama.cpp `llama-server` that Sonara starts and supervises.
//!
//! The "Managed by Sonara" mode of the llama.cpp assistant provider. Sonara
//! starts `llama-server` on a free loopback port with the chosen GGUF, and a
//! second instance with `--embeddings` when an embedding model is chosen.
//! It waits for `GET /health` to answer 200, restarts a server that exits (at
//! most `MAX_RESTARTS` times a minute), and stops both on request and when
//! the app exits.
//!
//! The program to run is never named by the webview: it is found on PATH or
//! picked with the native file picker, and remembered in
//! `<app data>/llama-server.json`.

use crate::process_tree;
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Stdio};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, Instant};

const SETTINGS_FILE: &str = "llama-server.json";
const LOG_LINES: usize = 40;
const LOG_LINE_CHARS: usize = 400;
pub(crate) const MAX_RESTARTS: usize = 2;

/// How long to wait and how often to look. Tests shorten these.
#[derive(Clone, Copy, Debug)]
pub(crate) struct Timing {
    pub(crate) ready_timeout: Duration,
    pub(crate) poll: Duration,
    pub(crate) restart_window: Duration,
}

impl Default for Timing {
    fn default() -> Self {
        Self {
            ready_timeout: Duration::from_secs(60),
            poll: Duration::from_millis(250),
            restart_window: Duration::from_secs(60),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub(crate) enum ServerState {
    Stopped,
    Starting,
    Ready,
    Failed,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ServerStatus {
    pub(crate) state: ServerState,
    /// OpenAI-compatible base URL of the chat server, once ready.
    pub(crate) endpoint: Option<String>,
    pub(crate) embedding_endpoint: Option<String>,
    pub(crate) model: Option<String>,
    pub(crate) error: Option<String>,
    /// The last lines the servers printed, for a failure.
    pub(crate) log_tail: Vec<String>,
    pub(crate) restarts: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct StartRequest {
    pub(crate) executable: PathBuf,
    pub(crate) model: PathBuf,
    pub(crate) embedding_model: Option<PathBuf>,
    pub(crate) context_size: Option<u32>,
    pub(crate) threads: Option<u32>,
}

type Log = Arc<Mutex<VecDeque<String>>>;

struct Instance {
    child: Child,
    port: u16,
    log: Log,
}

impl Instance {
    fn endpoint(&self) -> String {
        format!("http://127.0.0.1:{}/v1", self.port)
    }

    fn exited(&mut self) -> bool {
        !matches!(self.child.try_wait(), Ok(None))
    }
}

impl Drop for Instance {
    fn drop(&mut self) {
        process_tree::kill_and_reap(&mut self.child);
    }
}

struct Inner {
    state: ServerState,
    error: Option<String>,
    /// Bumped by every start and stop; a supervisor of an older generation
    /// stops supervising.
    generation: u64,
    request: Option<StartRequest>,
    chat: Option<Instance>,
    embed: Option<Instance>,
    restarts: VecDeque<Instant>,
    log_tail: Vec<String>,
}

pub(crate) struct LlamaServers {
    inner: Arc<Mutex<Inner>>,
    timing: Timing,
}

impl Default for LlamaServers {
    fn default() -> Self {
        Self::with_timing(Timing::default())
    }
}

fn lock(inner: &Mutex<Inner>) -> MutexGuard<'_, Inner> {
    inner.lock().unwrap_or_else(|poison| poison.into_inner())
}

impl LlamaServers {
    pub(crate) fn with_timing(timing: Timing) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Inner {
                state: ServerState::Stopped,
                error: None,
                generation: 0,
                request: None,
                chat: None,
                embed: None,
                restarts: VecDeque::new(),
                log_tail: Vec::new(),
            })),
            timing,
        }
    }

    pub(crate) fn status(&self) -> ServerStatus {
        let inner = lock(&self.inner);
        let ready = inner.state == ServerState::Ready;
        let mut log_tail = inner.log_tail.clone();
        if let Some(chat) = &inner.chat {
            log_tail = snapshot(&chat.log);
        }
        ServerStatus {
            state: inner.state,
            endpoint: inner
                .chat
                .as_ref()
                .filter(|_| ready)
                .map(Instance::endpoint),
            embedding_endpoint: inner
                .embed
                .as_ref()
                .filter(|_| ready)
                .map(Instance::endpoint),
            model: inner
                .request
                .as_ref()
                .and_then(|request| request.model.file_name())
                .map(|name| name.to_string_lossy().into_owned()),
            error: inner.error.clone(),
            log_tail,
            restarts: inner.restarts.len(),
        }
    }

    /// Start the servers, replacing any that run. Returns once they are
    /// spawned; `status` reports when they are ready.
    pub(crate) fn start(&self, request: StartRequest) -> Result<ServerStatus, String> {
        validate(&request)?;
        let generation = {
            let mut inner = lock(&self.inner);
            inner.generation += 1;
            inner.chat = None;
            inner.embed = None;
            inner.restarts.clear();
            inner.error = None;
            inner.log_tail.clear();
            inner.request = Some(request);
            inner.generation
        };
        self.launch(generation)?;
        let inner = Arc::clone(&self.inner);
        let timing = self.timing;
        thread::Builder::new()
            .name("sonara-llama-server".to_owned())
            .spawn(move || supervise(&inner, timing, generation))
            .map_err(|error| format!("Could not watch llama-server: {error}"))?;
        Ok(self.status())
    }

    /// Spawn the instances for the current request, as `Starting`.
    fn launch(&self, generation: u64) -> Result<(), String> {
        launch(&self.inner, generation)
    }

    pub(crate) fn stop(&self) {
        let mut inner = lock(&self.inner);
        inner.generation += 1;
        inner.chat = None;
        inner.embed = None;
        inner.state = ServerState::Stopped;
        inner.error = None;
    }
}

fn launch(shared: &Mutex<Inner>, generation: u64) -> Result<(), String> {
    let mut inner = lock(shared);
    if inner.generation != generation {
        return Ok(());
    }
    let Some(request) = inner.request.clone() else {
        return Err("Choose a model for llama-server first.".to_owned());
    };
    inner.chat = None;
    inner.embed = None;
    let spawned = spawn_instance(&request, &request.model, false).and_then(|chat| {
        let embed = match &request.embedding_model {
            Some(model) => Some(spawn_instance(&request, model, true)?),
            None => None,
        };
        Ok((chat, embed))
    });
    match spawned {
        Ok((chat, embed)) => {
            inner.chat = Some(chat);
            inner.embed = embed;
            inner.state = ServerState::Starting;
            Ok(())
        }
        Err(error) => {
            inner.state = ServerState::Failed;
            inner.error = Some(error.clone());
            Err(error)
        }
    }
}

fn validate(request: &StartRequest) -> Result<(), String> {
    if !request.executable.is_file() {
        return Err("llama-server was not found. Choose the program in Settings.".to_owned());
    }
    for model in std::iter::once(&request.model).chain(request.embedding_model.as_ref()) {
        let gguf = model
            .extension()
            .is_some_and(|ext| ext.eq_ignore_ascii_case("gguf"));
        if !gguf || !model.is_file() {
            return Err(format!("{} is not a GGUF model file.", model.display()));
        }
    }
    Ok(())
}

/// A port the OS reports free now. Another process could take it before
/// llama-server binds it; that shows as a failed start, which restarts.
fn free_port() -> Result<u16, String> {
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
        .map_err(|error| format!("Could not find a free port for llama-server: {error}"))?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("Could not find a free port for llama-server: {error}"))
}

fn spawn_instance(
    request: &StartRequest,
    model: &Path,
    embeddings: bool,
) -> Result<Instance, String> {
    let port = free_port()?;
    let mut command = process_tree::worker_command(&request.executable, false);
    command
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .arg("-m")
        .arg(model)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if embeddings {
        command.arg("--embeddings");
    }
    if let Some(context) = request.context_size {
        command.arg("-c").arg(context.to_string());
    }
    if let Some(threads) = request.threads {
        command.arg("-t").arg(threads.to_string());
    }
    let mut child = command
        .spawn()
        .map_err(|error| format!("Could not start llama-server: {error}"))?;
    if let Err(error) = process_tree::adopt(&child) {
        process_tree::kill_and_reap(&mut child);
        return Err(error);
    }
    let log: Log = Arc::new(Mutex::new(VecDeque::new()));
    if let Some(stdout) = child.stdout.take() {
        collect_log(stdout, Arc::clone(&log));
    }
    if let Some(stderr) = child.stderr.take() {
        collect_log(stderr, Arc::clone(&log));
    }
    Ok(Instance { child, port, log })
}

fn collect_log(stream: impl Read + Send + 'static, log: Log) {
    let _ = thread::Builder::new()
        .name("sonara-llama-log".to_owned())
        .spawn(move || {
            for line in BufReader::new(stream).lines() {
                let Ok(line) = line else { break };
                let line: String = line.chars().take(LOG_LINE_CHARS).collect();
                let mut log = log.lock().unwrap_or_else(|poison| poison.into_inner());
                if log.len() == LOG_LINES {
                    log.pop_front();
                }
                log.push_back(line);
            }
        });
}

fn snapshot(log: &Log) -> Vec<String> {
    log.lock()
        .unwrap_or_else(|poison| poison.into_inner())
        .iter()
        .cloned()
        .collect()
}

/// True when `GET /health` on the port answers 200.
fn healthy(port: u16) -> bool {
    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(500)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    let request = format!("GET /health HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut status_line = String::new();
    BufReader::new(stream.take(256))
        .read_line(&mut status_line)
        .is_ok()
        && status_line.split_whitespace().nth(1) == Some("200")
}

enum Check {
    /// Superseded by a newer start or a stop.
    Gone,
    Exited,
    Running {
        ports: Vec<u16>,
    },
}

fn check(shared: &Mutex<Inner>, generation: u64) -> Check {
    let mut inner = lock(shared);
    if inner.generation != generation {
        return Check::Gone;
    }
    let mut ports = Vec::new();
    let inner = &mut *inner;
    for instance in [inner.chat.as_mut(), inner.embed.as_mut()]
        .into_iter()
        .flatten()
    {
        if instance.exited() {
            return Check::Exited;
        }
        ports.push(instance.port);
    }
    if ports.is_empty() {
        return Check::Exited;
    }
    Check::Running { ports }
}

fn supervise(shared: &Mutex<Inner>, timing: Timing, generation: u64) {
    let mut started = Instant::now();
    loop {
        thread::sleep(timing.poll);
        let ports = match check(shared, generation) {
            Check::Gone => return,
            Check::Running { ports } => ports,
            Check::Exited => {
                if !restart(shared, timing, generation) {
                    return;
                }
                started = Instant::now();
                continue;
            }
        };
        let state = lock(shared).state;
        if state == ServerState::Starting {
            // Health is checked without the lock; a slow reply never blocks status.
            if ports.iter().all(|port| healthy(*port)) {
                let mut inner = lock(shared);
                if inner.generation == generation {
                    inner.state = ServerState::Ready;
                }
            } else if started.elapsed() > timing.ready_timeout {
                fail(
                    shared,
                    generation,
                    format!(
                        "llama-server did not become ready within {} seconds.",
                        timing.ready_timeout.as_secs()
                    ),
                );
                return;
            }
        }
    }
}

/// A server exited: start it again, unless it has already been restarted
/// `MAX_RESTARTS` times within the window. Returns false when giving up.
fn restart(shared: &Mutex<Inner>, timing: Timing, generation: u64) -> bool {
    {
        let mut inner = lock(shared);
        if inner.generation != generation {
            return false;
        }
        let now = Instant::now();
        while inner
            .restarts
            .front()
            .is_some_and(|at| now.duration_since(*at) > timing.restart_window)
        {
            inner.restarts.pop_front();
        }
        if inner.restarts.len() >= MAX_RESTARTS {
            drop(inner);
            fail(
                shared,
                generation,
                "llama-server kept exiting, so Sonara stopped restarting it.".to_owned(),
            );
            return false;
        }
        inner.restarts.push_back(now);
        // Keep what the exited server printed.
        if let Some(chat) = &inner.chat {
            inner.log_tail = snapshot(&chat.log);
        }
    }
    launch(shared, generation).is_ok()
}

fn fail(shared: &Mutex<Inner>, generation: u64, error: String) {
    let mut inner = lock(shared);
    if inner.generation != generation {
        return;
    }
    if let Some(chat) = &inner.chat {
        let tail = snapshot(&chat.log);
        if !tail.is_empty() {
            inner.log_tail = tail;
        }
    }
    inner.chat = None;
    inner.embed = None;
    inner.state = ServerState::Failed;
    inner.error = Some(error);
}

#[derive(Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct Settings {
    executable: Option<PathBuf>,
}

/// The llama-server Sonara will run: the one picked in Settings, else the
/// first `llama-server` on PATH.
pub(crate) fn find_executable(app_data: &Path) -> Option<PathBuf> {
    let saved = std::fs::read(app_data.join(SETTINGS_FILE))
        .ok()
        .and_then(|bytes| serde_json::from_slice::<Settings>(&bytes).ok())
        .and_then(|settings| settings.executable)
        .filter(|path| path.is_file());
    saved.or_else(|| {
        let name = if cfg!(windows) {
            "llama-server.exe"
        } else {
            "llama-server"
        };
        std::env::split_paths(&std::env::var_os("PATH")?)
            .map(|dir| dir.join(name))
            .find(|path| path.is_file())
    })
}

pub(crate) fn save_executable(app_data: &Path, executable: &Path) -> Result<(), String> {
    if !executable.is_file() {
        return Err("That is not a program file.".to_owned());
    }
    std::fs::create_dir_all(app_data)
        .map_err(|error| format!("Could not save the llama-server choice: {error}"))?;
    let settings = Settings {
        executable: Some(executable.to_path_buf()),
    };
    crate::session::atomic_write_json(&app_data.join(SETTINGS_FILE), &settings)
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use crate::make_job_id;
    use std::os::unix::fs::PermissionsExt;

    /// A stand-in for llama-server: answers /health on --port, after a short
    /// "model load" that returns 503. With `crash`, exits right away.
    fn fake_server(dir: &Path, crash: bool) -> PathBuf {
        let script = dir.join("llama-server");
        let body = if crash {
            "import sys\nprint('loading model failed', flush=True)\nsys.exit(1)\n".to_owned()
        } else {
            r#"import sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
port = int(sys.argv[sys.argv.index("--port") + 1])
started = time.time()
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code = 200 if time.time() - started > 0.3 else 503
        self.send_response(code); self.end_headers()
    def log_message(self, *args): pass
print("server listening", flush=True)
HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"#
            .to_owned()
        };
        std::fs::write(&script, format!("#!/usr/bin/env python3\n{body}")).unwrap();
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
        script
    }

    fn request(dir: &Path, executable: PathBuf, embeddings: bool) -> StartRequest {
        let model = dir.join("chat.gguf");
        std::fs::write(&model, b"gguf").unwrap();
        let embedding_model = embeddings.then(|| {
            let path = dir.join("embed.gguf");
            std::fs::write(&path, b"gguf").unwrap();
            path
        });
        StartRequest {
            executable,
            model,
            embedding_model,
            context_size: Some(2048),
            threads: None,
        }
    }

    fn fast() -> Timing {
        Timing {
            ready_timeout: Duration::from_secs(10),
            poll: Duration::from_millis(50),
            restart_window: Duration::from_secs(60),
        }
    }

    fn wait_for(servers: &LlamaServers, state: ServerState) -> ServerStatus {
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            let status = servers.status();
            if status.state == state || Instant::now() > deadline {
                return status;
            }
            thread::sleep(Duration::from_millis(50));
        }
    }

    #[test]
    fn a_managed_server_becomes_ready_and_stops() {
        let dir = std::env::temp_dir().join(format!("sonara-llama-{}", make_job_id()));
        std::fs::create_dir_all(&dir).unwrap();
        let servers = LlamaServers::with_timing(fast());
        let started = servers
            .start(request(&dir, fake_server(&dir, false), true))
            .unwrap();
        assert_eq!(started.state, ServerState::Starting);
        assert_eq!(started.endpoint, None, "no endpoint before it is ready");

        let ready = wait_for(&servers, ServerState::Ready);
        assert_eq!(ready.state, ServerState::Ready, "{ready:?}");
        let endpoint = ready.endpoint.unwrap();
        assert!(endpoint.starts_with("http://127.0.0.1:") && endpoint.ends_with("/v1"));
        assert_ne!(ready.embedding_endpoint.unwrap(), endpoint);
        assert_eq!(ready.model.as_deref(), Some("chat.gguf"));

        servers.stop();
        let port: u16 = endpoint[17..endpoint.len() - 3].parse().unwrap();
        assert_eq!(servers.status().state, ServerState::Stopped);
        assert!(!healthy(port), "the server process is gone");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_server_that_keeps_exiting_is_restarted_twice_then_reported() {
        let dir = std::env::temp_dir().join(format!("sonara-llama-{}", make_job_id()));
        std::fs::create_dir_all(&dir).unwrap();
        let servers = LlamaServers::with_timing(fast());
        servers
            .start(request(&dir, fake_server(&dir, true), false))
            .unwrap();
        let failed = wait_for(&servers, ServerState::Failed);
        assert_eq!(failed.state, ServerState::Failed);
        assert_eq!(failed.restarts, MAX_RESTARTS);
        assert!(failed.error.unwrap().contains("kept exiting"));
        assert_eq!(failed.log_tail, vec!["loading model failed".to_owned()]);
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Opt-in: SONARA_LLAMA_SERVER_GGUF=/path/model.gguf with llama-server
    /// on PATH. Starts the real server, asks one question, and stops it.
    #[test]
    fn a_real_llama_server_answers_when_ready() {
        let Some(model) = std::env::var_os("SONARA_LLAMA_SERVER_GGUF").map(PathBuf::from) else {
            return;
        };
        let executable = find_executable(Path::new("/nonexistent")).expect("llama-server on PATH");
        let servers = LlamaServers::with_timing(Timing {
            ready_timeout: Duration::from_secs(180),
            ..Timing::default()
        });
        servers
            .start(StartRequest {
                executable,
                model,
                embedding_model: None,
                context_size: Some(2048),
                threads: None,
            })
            .unwrap();
        let deadline = Instant::now() + Duration::from_secs(200);
        let status = loop {
            let status = servers.status();
            if status.state != ServerState::Starting || Instant::now() > deadline {
                break status;
            }
            thread::sleep(Duration::from_millis(250));
        };
        assert_eq!(status.state, ServerState::Ready, "{status:?}");
        let endpoint = status.endpoint.unwrap();
        let port: u16 = endpoint[17..endpoint.len() - 3].parse().unwrap();
        let body = r#"{"messages":[{"role":"user","content":"Reply with the word ready."}],"max_tokens":8}"#;
        let mut stream = TcpStream::connect((Ipv4Addr::LOCALHOST, port)).unwrap();
        write!(
            stream,
            "POST /v1/chat/completions HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}",
            body.len()
        )
        .unwrap();
        let mut reply = String::new();
        stream.read_to_string(&mut reply).unwrap();
        assert!(
            reply.starts_with("HTTP/1.1 200") || reply.starts_with("HTTP/1.0 200"),
            "{reply}"
        );
        assert!(reply.contains("\"choices\""), "{reply}");
        servers.stop();
        assert!(!healthy(port));
    }

    #[test]
    fn bad_requests_are_refused_before_anything_runs() {
        let dir = std::env::temp_dir().join(format!("sonara-llama-{}", make_job_id()));
        std::fs::create_dir_all(&dir).unwrap();
        let servers = LlamaServers::with_timing(fast());
        let mut bad = request(&dir, fake_server(&dir, false), false);
        bad.model = dir.join("model.bin");
        std::fs::write(&bad.model, b"x").unwrap();
        assert!(servers
            .start(bad.clone())
            .unwrap_err()
            .contains("not a GGUF"));
        bad.executable = dir.join("missing");
        assert!(servers.start(bad).unwrap_err().contains("not found"));
        assert_eq!(servers.status().state, ServerState::Stopped);

        // The saved choice wins over PATH, and must be a file.
        assert!(save_executable(&dir, &dir.join("missing")).is_err());
        let program = fake_server(&dir, false);
        save_executable(&dir, &program).unwrap();
        assert_eq!(find_executable(&dir), Some(program));
        let _ = std::fs::remove_dir_all(&dir);
    }
}

use serde::{Deserialize, Serialize};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::net::{TcpListener, TcpStream};
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::path::{Component, Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter, Manager, State, WindowEvent};

const DEFAULT_FALLBACK_VOICE: &str = "en_US-ryan-medium";
const MAX_ERROR_LOG_BYTES: u64 = 16 * 1024;
const MAX_AUDIO_RESPONSE_BYTES: u64 = 64 * 1024 * 1024;
const MAX_HTTP_REQUEST_BYTES: usize = 16 * 1024;
const SUPPORTED_DOCUMENT_EXTENSIONS: &[&str] = &["pdf", "txt", "text", "md", "docx", "epub"];

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct VoiceInfo {
    pub id: String,
    pub name: String,
    pub quality: String,
    pub language: String,
    pub is_default: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct LlmConfigInput {
    pub provider: String,
    pub endpoint: Option<String>,
    pub model: Option<String>,
    pub api_key: Option<String>,
    pub temperature: Option<f64>,
    pub max_tokens: Option<u32>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ChatMessageInput {
    pub role: String,
    pub content: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct LlmTestResult {
    pub ok: bool,
    pub provider: Option<String>,
    pub model: Option<String>,
    pub latency_ms: Option<u64>,
    pub response: Option<String>,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct LlmChatResult {
    pub ok: bool,
    pub answer: Option<String>,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct LlmSummarizeResult {
    pub ok: bool,
    pub summary: Option<String>,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct PronunciationOverrideSuggestion {
    pub source: String,
    pub spoken: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct NarrationEnhancement {
    pub spoken_text: String,
    pub notes: Vec<String>,
    pub suggested_overrides: Vec<PronunciationOverrideSuggestion>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct LlmEnhanceResult {
    pub ok: bool,
    pub enhancement: Option<NarrationEnhancement>,
    pub error: Option<String>,
}

#[derive(Default)]
struct AppState {
    selected_document: Mutex<Option<PathBuf>>,
    active: Mutex<Option<ActiveJob>>,
    session: Mutex<Option<ReaderSession>>,
}

struct AudioServer {
    base_url: String,
    stopped: Arc<AtomicBool>,
    thread: Mutex<Option<thread::JoinHandle<()>>>,
}

struct ActiveJob {
    id: String,
    child: Arc<Mutex<Child>>,
    cancelled: Arc<AtomicBool>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct ReaderChunk {
    audio_file: String,
    duration_seconds: f64,
    pause_after_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct ReaderSession {
    source_name: String,
    source_sha256: String,
    narration_ruleset_version: String,
    voice: String,
    sample_rate: u32,
    channels: u16,
    sample_width_bytes: u16,
    chunks: Vec<ReaderChunk>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct FrontendSession {
    source_name: String,
    source_sha256: String,
    narration_ruleset_version: String,
    voice: String,
    sample_rate: u32,
    channels: u16,
    sample_width_bytes: u16,
    audio_base_url: String,
    chunks: Vec<FrontendChunk>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct FrontendChunk {
    duration_seconds: f64,
    pause_after_ms: u64,
}

impl FrontendSession {
    fn from_session(session: &ReaderSession, audio_base_url: &str) -> Self {
        Self {
            source_name: session.source_name.clone(),
            source_sha256: session.source_sha256.clone(),
            narration_ruleset_version: session.narration_ruleset_version.clone(),
            voice: session.voice.clone(),
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

impl AudioServer {
    fn start(app: AppHandle) -> std::io::Result<Self> {
        let listener = TcpListener::bind(("127.0.0.1", 0))?;
        listener.set_nonblocking(true)?;
        let address = listener.local_addr()?;
        let expected_host = format!("127.0.0.1:{}", address.port());
        let mut random = [0_u8; 32];
        getrandom::fill(&mut random).map_err(|error| {
            std::io::Error::other(format!(
                "Could not create a local audio access token: {error}"
            ))
        })?;
        let token = random
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let base_url = format!("http://127.0.0.1:{}/v1/{token}", address.port());
        let stopped = Arc::new(AtomicBool::new(false));
        let thread_stopped = Arc::clone(&stopped);
        let thread_token = token.clone();
        let thread_host = expected_host;
        let worker = thread::Builder::new()
            .name("sonara-local-audio-http".to_owned())
            .spawn(move || {
                while !thread_stopped.load(Ordering::SeqCst) {
                    match listener.accept() {
                        Ok((stream, _)) => {
                            serve_audio_http_request(&app, &thread_token, &thread_host, stream)
                        }
                        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                            thread::sleep(Duration::from_millis(20));
                        }
                        Err(_) => break,
                    }
                }
            })?;
        Ok(Self {
            base_url,
            stopped,
            thread: Mutex::new(Some(worker)),
        })
    }

    fn stop(&self) {
        self.stopped.store(true, Ordering::SeqCst);
        if let Ok(mut worker) = self.thread.lock() {
            if let Some(worker) = worker.take() {
                let _ = worker.join();
            }
        }
    }
}

impl Drop for AudioServer {
    fn drop(&mut self) {
        self.stop();
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct Progress {
    version: u8,
    source_sha256: String,
    segment: usize,
    offset_seconds: f64,
    playback_rate: f64,
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
fn preview_narration(
    state: State<'_, AppState>,
    voice: Option<String>,
    expand_dates: bool,
    expand_citations: bool,
) -> Result<serde_json::Value, String> {
    let selected_path = state
        .selected_document
        .lock()
        .map_err(|_| "Document selection state is unavailable.".to_owned())?
        .clone()
        .ok_or_else(|| "Choose a document before previewing narration.".to_owned())?;
    let document = validate_document(&selected_path)?;
    let runtime = resolve_runtime()?;
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
    let mut command = Command::new(&runtime.python);
    let mut args = vec!["read", "--preview"];
    if expand_dates {
        args.push("--expand-dates");
    }
    if expand_citations {
        args.push("--expand-citations");
    }
    let output = command
        .env_clear()
        .env("PATH", std::env::var_os("PATH").unwrap_or_default())
        .env("HOME", std::env::var_os("HOME").unwrap_or_default())
        .env("LANG", std::env::var_os("LANG").unwrap_or_default())
        .env("LC_ALL", std::env::var_os("LC_ALL").unwrap_or_default())
        .current_dir(&runtime.project_root)
        .arg(&runtime.script)
        .args(args)
        .arg(&document)
        .arg("--voice")
        .arg(&selected_voice)
        .arg("--data-dir")
        .arg(&runtime.model_dir)
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
}

#[cfg(target_os = "linux")]
fn choose_document_path() -> Result<Option<PathBuf>, String> {
    let zenity_res = Command::new("zenity")
        .arg("--file-selection")
        .arg("--title=Open a Document in Sonara")
        .arg("--file-filter=Supported Documents | *.pdf *.txt *.text *.md *.docx *.epub")
        .arg("--file-filter=All Files | *")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output();

    let output = match zenity_res {
        Ok(out) => out,
        Err(_) => Command::new("kdialog")
            .arg("--getopenfilename")
            .arg(".")
            .arg("*.pdf *.txt *.text *.md *.docx *.epub|Supported Documents (*.pdf *.txt *.text *.md *.docx *.epub)\n*|All Files (*)")
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .output()
            .map_err(|error| {
                format!(
                    "Could not open the system file picker ({error}). Install Zenity or Kdialog."
                )
            })?,
    };

    if !output.status.success() {
        if output.stdout.is_empty() {
            return Ok(None);
        }
        return Err(format!(
            "The system file picker exited with status {}.",
            output.status
        ));
    }
    let selected = String::from_utf8(output.stdout)
        .map_err(|_| "The system file picker returned a non-UTF-8 path.".to_owned())?;
    let selected = selected.trim_end_matches(['\r', '\n']);
    if selected.is_empty() {
        Ok(None)
    } else {
        Ok(Some(PathBuf::from(selected)))
    }
}

#[cfg(target_os = "macos")]
fn choose_document_path() -> Result<Option<PathBuf>, String> {
    let script = r#"POSIX path of (choose file with prompt "Open a Document in Sonara" of type {"pdf", "txt", "text", "md", "docx", "epub", "public.plain-text", "net.daringfireball.markdown", "com.adobe.pdf", "org.openxmlformats.wordprocessingml.document", "org.idpf.epub-folder"})"#;
    let output = Command::new("osascript")
        .arg("-e")
        .arg(script)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .map_err(|err| format!("Could not open macOS file picker: {err}"))?;
    if !output.status.success() {
        return Ok(None);
    }
    let selected =
        String::from_utf8(output.stdout).map_err(|_| "Picker returned non-UTF-8 path.")?;
    let selected = selected.trim();
    if selected.is_empty() {
        Ok(None)
    } else {
        Ok(Some(PathBuf::from(selected)))
    }
}

#[cfg(target_os = "windows")]
fn choose_document_path() -> Result<Option<PathBuf>, String> {
    let script = r#"
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Filter = "Supported Documents (*.pdf;*.txt;*.text;*.md;*.docx;*.epub)|*.pdf;*.txt;*.text;*.md;*.docx;*.epub|All files (*.*)|*.*"
$dialog.Title = "Open a Document in Sonara"
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    Write-Output $dialog.FileName
}
"#;
    let output = Command::new("powershell")
        .arg("-NoProfile")
        .arg("-Command")
        .arg(script)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .map_err(|err| format!("Could not open Windows file picker: {err}"))?;
    if !output.status.success() {
        return Ok(None);
    }
    let selected =
        String::from_utf8(output.stdout).map_err(|_| "Picker returned non-UTF-8 path.")?;
    let selected = selected.trim();
    if selected.is_empty() {
        Ok(None)
    } else {
        Ok(Some(PathBuf::from(selected)))
    }
}

#[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
fn choose_document_path() -> Result<Option<PathBuf>, String> {
    Err("File selection is not supported on this operating system.".to_owned())
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

#[tauri::command]
fn list_voices() -> Result<Vec<VoiceInfo>, String> {
    let runtime = resolve_runtime()?;
    discover_voices(&runtime.model_dir)
}

fn discover_voices(model_dir: &Path) -> Result<Vec<VoiceInfo>, String> {
    let mut voices = Vec::new();
    let entries =
        fs::read_dir(model_dir).map_err(|e| format!("Could not read voice directory: {e}"))?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_file() && path.extension().and_then(|s| s.to_str()) == Some("onnx") {
            let Some(stem) = path.file_stem().and_then(|s| s.to_str()) else {
                continue;
            };
            let json_path = model_dir.join(format!("{stem}.onnx.json"));
            if json_path.is_file() {
                let (name, quality, language) = parse_voice_metadata(&json_path, stem);
                voices.push(VoiceInfo {
                    id: stem.to_string(),
                    name,
                    quality,
                    language,
                    is_default: false,
                });
            }
        }
    }
    voices.sort_by(|a, b| {
        voice_priority(&a.id)
            .cmp(&voice_priority(&b.id))
            .then_with(|| a.id.cmp(&b.id))
    });
    if !voices.is_empty() {
        let default_idx = voices
            .iter()
            .position(|v| v.id == "en_US-ryan-medium")
            .or_else(|| voices.iter().position(|v| v.id == "en_US-lessac-medium"))
            .unwrap_or(0);
        if let Some(target) = voices.get_mut(default_idx) {
            target.is_default = true;
        }
    }
    Ok(voices)
}

fn voice_priority(id: &str) -> usize {
    match id {
        "en_US-ryan-medium" => 0,
        "en_US-lessac-medium" => 1,
        "en_US-bryce-medium" => 2,
        "en_US-john-medium" => 3,
        _ => 10,
    }
}

fn parse_voice_metadata(json_path: &Path, id: &str) -> (String, String, String) {
    let friendly_name = match id {
        "en_US-ryan-medium" => "Ryan (American Male · Natural)".to_string(),
        "en_US-lessac-medium" => "Lessac (American Female · Expressive)".to_string(),
        "en_US-bryce-medium" => "Bryce (American Male · Narrative)".to_string(),
        "en_US-john-medium" => "John (American Male · LibriVox)".to_string(),
        _ => id.to_string(),
    };
    let Ok(content) = fs::read_to_string(json_path) else {
        return (friendly_name, "medium".to_string(), "en_US".to_string());
    };
    let Ok(val): Result<serde_json::Value, _> = serde_json::from_str(&content) else {
        return (friendly_name, "medium".to_string(), "en_US".to_string());
    };
    let quality = val
        .pointer("/audio/quality")
        .and_then(|v| v.as_str())
        .unwrap_or("medium")
        .to_string();
    let language = val
        .pointer("/language/code")
        .and_then(|v| v.as_str())
        .unwrap_or("en_US")
        .to_string();
    (friendly_name, quality, language)
}

#[tauri::command]
fn start_reading(
    app: AppHandle,
    state: State<'_, AppState>,
    voice: Option<String>,
    variation: Option<String>,
    expand_dates: Option<bool>,
    expand_citations: Option<bool>,
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

    let runtime = resolve_runtime()?;
    let selected_voice = match voice.as_deref() {
        Some(v) if !v.trim().is_empty() => {
            let candidate = v.trim();
            if !candidate
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
            {
                return Err("Invalid voice name.".to_owned());
            }
            if !runtime
                .model_dir
                .join(format!("{candidate}.onnx"))
                .is_file()
                || !runtime
                    .model_dir
                    .join(format!("{candidate}.onnx.json"))
                    .is_file()
            {
                return Err(format!(
                    "Selected voice '{candidate}' is not installed in {}.",
                    runtime.model_dir.display()
                ));
            }
            candidate.to_string()
        }
        _ => {
            let voices = discover_voices(&runtime.model_dir)?;
            voices
                .iter()
                .find(|v| v.is_default)
                .map(|v| v.id.clone())
                .unwrap_or_else(|| DEFAULT_FALLBACK_VOICE.to_string())
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

    let child = spawn_sonara_worker(
        &runtime,
        &document,
        &output_dir,
        &selected_voice,
        &selected_variation,
        expand_dates.unwrap_or(false),
        expand_citations.unwrap_or(false),
        log,
        error_log,
    )
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

fn invoke_llm_rpc(request: &serde_json::Value) -> Result<serde_json::Value, String> {
    let runtime = resolve_runtime()?;
    let llm_script = runtime.project_root.join("llm_client.py");
    if !llm_script.is_file() {
        return Err("LLM client script (llm_client.py) was not found in project root.".to_owned());
    }

    let mut child = Command::new(&runtime.python)
        .arg(&llm_script)
        .arg("rpc")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn LLM client process: {e}"))?;

    let stdin_payload = serde_json::to_vec(request)
        .map_err(|e| format!("Failed to serialize LLM RPC request: {e}"))?;

    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(&stdin_payload)
            .map_err(|e| format!("Failed to write to LLM client stdin: {e}"))?;
    }

    let output = child
        .wait_with_output()
        .map_err(|e| format!("Failed waiting for LLM client: {e}"))?;

    let stdout_str = String::from_utf8_lossy(&output.stdout);
    if stdout_str.trim().is_empty() {
        let stderr_str = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "LLM client produced no output. Stderr: {stderr_str}"
        ));
    }

    let result: serde_json::Value = serde_json::from_str(stdout_str.trim()).map_err(|e| {
        format!("Failed to parse LLM client response JSON: {e}. Raw stdout: {stdout_str}")
    })?;

    Ok(result)
}

#[tauri::command]
fn llm_test_connection(config: LlmConfigInput) -> Result<LlmTestResult, String> {
    let req = serde_json::json!({
        "action": "test_connection",
        "config": config,
    });
    let val = invoke_llm_rpc(&req)?;
    let result: LlmTestResult = serde_json::from_value(val)
        .map_err(|e| format!("Failed to decode LLM test connection response: {e}"))?;
    Ok(result)
}

#[tauri::command]
fn llm_chat(
    config: LlmConfigInput,
    question: String,
    context: Option<String>,
    history: Option<Vec<ChatMessageInput>>,
) -> Result<LlmChatResult, String> {
    let req = serde_json::json!({
        "action": "chat",
        "config": config,
        "question": question,
        "context": context.unwrap_or_default(),
        "history": history.unwrap_or_default(),
    });
    let val = invoke_llm_rpc(&req)?;
    let result: LlmChatResult = serde_json::from_value(val)
        .map_err(|e| format!("Failed to decode LLM chat response: {e}"))?;
    Ok(result)
}

#[tauri::command]
fn llm_summarize(
    config: LlmConfigInput,
    text: String,
    mode: Option<String>,
) -> Result<LlmSummarizeResult, String> {
    let req = serde_json::json!({
        "action": "summarize",
        "config": config,
        "text": text,
        "mode": mode.unwrap_or_else(|| "summary".to_string()),
    });
    let val = invoke_llm_rpc(&req)?;
    let result: LlmSummarizeResult = serde_json::from_value(val)
        .map_err(|e| format!("Failed to decode LLM summarize response: {e}"))?;
    Ok(result)
}

#[tauri::command]
fn llm_enhance_script(config: LlmConfigInput, text: String) -> Result<LlmEnhanceResult, String> {
    let req = serde_json::json!({
        "action": "enhance_narration",
        "config": config,
        "text": text,
    });
    let val = invoke_llm_rpc(&req)?;
    let result: LlmEnhanceResult = serde_json::from_value(val)
        .map_err(|e| format!("Failed to decode LLM narration enhance response: {e}"))?;
    Ok(result)
}

#[tauri::command]
fn get_document_text(
    app: AppHandle,
    state: State<'_, AppState>,
    path: Option<String>,
) -> Result<String, String> {
    let target = if let Some(p) = path.filter(|s| !s.trim().is_empty()) {
        p
    } else {
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
    let val = invoke_llm_rpc(&req)?;
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
    }
    let audio_base_url = app.state::<AudioServer>().base_url.clone();
    let result =
        session_result.map(|session| FrontendSession::from_session(&session, &audio_base_url));
    let _ = app.emit("synthesis-finished", SynthesisFinished { job_id, result });
}

fn read_log_tail(path: &Path, max_bytes: u64) -> Option<String> {
    let mut file = File::open(path).ok()?;
    let len = file.metadata().ok()?.len();
    if len == 0 {
        return None;
    }
    let offset = len.saturating_sub(max_bytes);
    if offset > 0 {
        file.seek(SeekFrom::Start(offset)).ok()?;
    }
    let mut buffer = Vec::new();
    file.read_to_end(&mut buffer).ok()?;
    let text = String::from_utf8_lossy(&buffer);
    let trimmed = text.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_owned())
    }
}

fn extract_error_summary(detail: &str, limit: usize) -> String {
    let explicit_errors: Vec<&str> = detail
        .lines()
        .map(str::trim)
        .filter(|line| {
            (line.starts_with("sonara:") && !line.starts_with("sonara: review:"))
                || line.contains("Error")
                || line.contains("error:")
                || line.contains("failed:")
        })
        .collect();

    if !explicit_errors.is_empty() {
        return truncate_chars(&explicit_errors.join("\n"), limit);
    }

    let lines: Vec<&str> = detail
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .collect();
    if lines.len() > 10 {
        let last_lines = &lines[lines.len() - 10..];
        truncate_chars(&last_lines.join("\n"), limit)
    } else {
        truncate_chars(detail, limit)
    }
}

fn worker_failure_message(log_path: &Path, exit_code: Option<i32>) -> String {
    let detail = read_log_tail(log_path, MAX_ERROR_LOG_BYTES);
    match detail {
        Some(detail) => format!("Speech generation failed: {}", extract_error_summary(&detail, 4000)),
        None => format!("Speech generation failed (worker exit code {}). Check the local Python and Piper setup.", exit_code.map_or_else(|| "unknown".to_owned(), |code| code.to_string())),
    }
}

fn truncate_chars(value: &str, limit: usize) -> String {
    let mut chars = value.chars();
    let prefix: String = chars.by_ref().take(limit).collect();
    if chars.next().is_some() {
        format!("{prefix}…")
    } else {
        prefix
    }
}

fn load_reader_session(output_dir: &Path, source_path: &Path) -> Result<ReaderSession, String> {
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
        sample_rate,
        channels,
        sample_width_bytes,
        chunks,
    };
    atomic_write_json(&session_meta_path, &session)?;
    Ok(session)
}

fn load_saved_session(output_dir: &Path) -> Option<ReaderSession> {
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

struct RuntimePaths {
    project_root: PathBuf,
    python: PathBuf,
    script: PathBuf,
    model_dir: PathBuf,
}

fn spawn_sonara_worker(
    runtime: &RuntimePaths,
    document: &Path,
    output_dir: &Path,
    voice: &str,
    variation: &str,
    expand_dates: bool,
    expand_citations: bool,
    stdout: File,
    stderr: File,
) -> std::io::Result<Child> {
    let mut command = Command::new(&runtime.python);
    command
        .env_clear()
        .env("PATH", std::env::var_os("PATH").unwrap_or_default())
        .env("HOME", std::env::var_os("HOME").unwrap_or_default())
        .env("LANG", std::env::var_os("LANG").unwrap_or_default())
        .env("LC_ALL", std::env::var_os("LC_ALL").unwrap_or_default())
        .env(
            "LD_LIBRARY_PATH",
            std::env::var_os("LD_LIBRARY_PATH").unwrap_or_default(),
        )
        .current_dir(&runtime.project_root)
        .arg(&runtime.script)
        .arg("read")
        .arg(document)
        .arg("--voice")
        .arg(voice)
        .arg("--variation")
        .arg(variation)
        .arg("--data-dir")
        .arg(&runtime.model_dir)
        .arg("--output-dir")
        .arg(output_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .env("PYTHONUNBUFFERED", "1");
    if expand_dates {
        command.arg("--expand-dates");
    }
    if expand_citations {
        command.arg("--expand-citations");
    }
    #[cfg(unix)]
    command.process_group(0);
    command.spawn()
}

fn resolve_runtime() -> Result<RuntimePaths, String> {
    let repo_root = std::env::var_os("SONARA_PROJECT_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(".."));
    let root = repo_root
        .canonicalize()
        .map_err(|error| format!("Could not locate the Sonara project directory: {error}"))?;
    let script = root.join("sonara.py");
    if !script.is_file() {
        return Err(
            "The Sonara Python engine is missing. Set SONARA_PROJECT_ROOT to the project checkout."
                .to_owned(),
        );
    }
    let python = std::env::var_os("SONARA_PYTHON")
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join(".venv/bin/python"));
    if !python.is_file() {
        return Err(format!("Python environment was not found at {}. Set SONARA_PYTHON to the environment's Python executable.", python.display()));
    }
    // Keep the venv's `bin/python` symlink intact: resolving it to the system
    // interpreter discards the virtual environment's site-packages.
    let python = if python.is_absolute() {
        python
    } else {
        std::env::current_dir()
            .map_err(|error| {
                format!("Could not resolve the configured Python executable: {error}")
            })?
            .join(python)
    };
    let model_dir = std::env::var_os("SONARA_MODEL_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("models/piper"));
    let has_any_model = fs::read_dir(&model_dir)
        .ok()
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
        .any(|entry| {
            let p = entry.path();
            p.is_file()
                && p.extension().and_then(|e| e.to_str()) == Some("onnx")
                && model_dir
                    .join(format!("{}.json", p.file_name().unwrap().to_string_lossy()))
                    .is_file()
        });
    if !has_any_model {
        return Err(format!(
            "No Piper voice models found in {}. Ensure .onnx and .onnx.json files exist.",
            model_dir.display()
        ));
    }
    let model_dir = model_dir.canonicalize().map_err(|error| {
        format!("Could not access the configured Piper voice directory: {error}")
    })?;
    Ok(RuntimePaths {
        project_root: root,
        python,
        script,
        model_dir,
    })
}

fn progress_path(app: &AppHandle, source_sha256: &str) -> Result<PathBuf, String> {
    let root = app
        .path()
        .app_local_data_dir()
        .map_err(|error| format!("Could not find Sonara's local data directory: {error}"))?
        .join("progress");
    fs::create_dir_all(&root)
        .map_err(|error| format!("Could not create progress storage: {error}"))?;
    Ok(root.join(format!("{source_sha256}.json")))
}

fn atomic_write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
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

fn validate_hash(hash: &str) -> Result<(), String> {
    if hash.len() == 64 && hash.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        Ok(())
    } else {
        Err("Document identity is invalid.".to_owned())
    }
}

fn is_safe_relative_audio_path(path: &Path) -> bool {
    !path.as_os_str().is_empty()
        && !path.is_absolute()
        && path
            .components()
            .all(|item| matches!(item, Component::Normal(_)))
}

fn serve_audio_http_request(
    app: &AppHandle,
    token: &str,
    expected_host: &str,
    mut stream: TcpStream,
) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(3)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));
    let mut bytes = Vec::with_capacity(2048);
    let mut buffer = [0_u8; 2048];
    loop {
        match stream.read(&mut buffer) {
            Ok(0) => return,
            Ok(count) => {
                if bytes.len() + count > MAX_HTTP_REQUEST_BYTES {
                    write_audio_http_response(
                        &mut stream,
                        431,
                        "text/plain",
                        b"Request too large",
                        None,
                        None,
                    );
                    return;
                }
                bytes.extend_from_slice(&buffer[..count]);
                if bytes.windows(4).any(|window| window == b"\r\n\r\n") {
                    break;
                }
            }
            Err(_) => return,
        }
    }

    let request_text = String::from_utf8_lossy(&bytes);
    let mut lines = request_text.split("\r\n");
    let Some(request_line) = lines.next() else {
        write_audio_http_response(
            &mut stream,
            400,
            "text/plain",
            b"Malformed request",
            None,
            None,
        );
        return;
    };
    let mut request_parts = request_line.split_whitespace();
    let method = request_parts.next().unwrap_or_default();
    let path = request_parts.next().unwrap_or_default();
    let version = request_parts.next().unwrap_or_default();
    if (version != "HTTP/1.0" && version != "HTTP/1.1") || path.contains('?') {
        write_audio_http_response(
            &mut stream,
            400,
            "text/plain",
            b"Malformed request",
            None,
            None,
        );
        return;
    }
    if method != "GET" && method != "HEAD" {
        write_audio_http_response(
            &mut stream,
            405,
            "text/plain",
            b"Method not allowed",
            None,
            None,
        );
        return;
    }

    let mut host = None;
    let mut range = None;
    for line in lines {
        if line.is_empty() {
            break;
        }
        if let Some((name, value)) = line.split_once(':') {
            if name.eq_ignore_ascii_case("host") {
                host = Some(value.trim());
            }
            if name.eq_ignore_ascii_case("range") {
                range = Some(value.trim());
            }
        }
    }
    if host != Some(expected_host) {
        write_audio_http_response(
            &mut stream,
            421,
            "text/plain",
            b"Unexpected host",
            None,
            None,
        );
        return;
    }
    let (document_hash, index) = match parse_audio_route(path, token) {
        Ok(route) => route,
        Err(status) => {
            write_audio_http_response(
                &mut stream,
                status,
                "text/plain",
                b"Audio passage not found",
                None,
                None,
            );
            return;
        }
    };
    let session = match app.state::<AppState>().session.lock() {
        Ok(session) => session.clone(),
        Err(_) => {
            write_audio_http_response(
                &mut stream,
                500,
                "text/plain",
                b"Reader state unavailable",
                None,
                None,
            );
            return;
        }
    };
    let Some(session) = session.filter(|session| session.source_sha256 == document_hash) else {
        write_audio_http_response(
            &mut stream,
            404,
            "text/plain",
            b"Audio passage not found",
            None,
            None,
        );
        return;
    };
    let Some(chunk) = session.chunks.get(index) else {
        write_audio_http_response(
            &mut stream,
            404,
            "text/plain",
            b"Audio passage not found",
            None,
            None,
        );
        return;
    };
    let output_root = match app
        .path()
        .app_local_data_dir()
        .map(|path| path.join("reader-output").canonicalize())
    {
        Ok(Ok(path)) => path,
        _ => {
            write_audio_http_response(
                &mut stream,
                404,
                "text/plain",
                b"Generated audio unavailable",
                None,
                None,
            );
            return;
        }
    };
    let chunks_root = match output_root.join("chunks").canonicalize() {
        Ok(path) => path,
        Err(_) => {
            write_audio_http_response(
                &mut stream,
                404,
                "text/plain",
                b"Generated audio unavailable",
                None,
                None,
            );
            return;
        }
    };
    let audio_path = match PathBuf::from(&chunk.audio_file).canonicalize() {
        Ok(path) if path.starts_with(chunks_root) && path.is_file() => path,
        _ => {
            write_audio_http_response(
                &mut stream,
                404,
                "text/plain",
                b"Generated audio unavailable",
                None,
                None,
            );
            return;
        }
    };
    let mut file = match File::open(audio_path) {
        Ok(file) => file,
        Err(_) => {
            write_audio_http_response(
                &mut stream,
                404,
                "text/plain",
                b"Generated audio unavailable",
                None,
                None,
            );
            return;
        }
    };
    let file_length = match file.metadata() {
        Ok(metadata) if metadata.is_file() => metadata.len(),
        _ => {
            write_audio_http_response(
                &mut stream,
                404,
                "text/plain",
                b"Generated audio unavailable",
                None,
                None,
            );
            return;
        }
    };
    let (start, end, partial) = match range {
        Some(value) => match parse_byte_range(value, file_length) {
            Some((start, end)) => (start, end, true),
            None => {
                write_audio_http_response(
                    &mut stream,
                    416,
                    "audio/wav",
                    &[],
                    Some(format!("bytes */{file_length}")),
                    Some(0),
                );
                return;
            }
        },
        None => (0, file_length, false),
    };
    let content_length = end.saturating_sub(start);
    if content_length > MAX_AUDIO_RESPONSE_BYTES {
        write_audio_http_response(
            &mut stream,
            413,
            "text/plain",
            b"Audio passage too large",
            None,
            None,
        );
        return;
    }
    let is_head = method == "HEAD";
    let body = if is_head {
        Vec::new()
    } else {
        if file.seek(SeekFrom::Start(start)).is_err() {
            write_audio_http_response(
                &mut stream,
                500,
                "text/plain",
                b"Could not read audio",
                None,
                None,
            );
            return;
        }
        let mut body = Vec::with_capacity(content_length as usize);
        if file.take(content_length).read_to_end(&mut body).is_err()
            || body.len() as u64 != content_length
        {
            write_audio_http_response(
                &mut stream,
                500,
                "text/plain",
                b"Could not read audio",
                None,
                None,
            );
            return;
        }
        body
    };
    let content_range =
        partial.then(|| format!("bytes {start}-{}/{file_length}", end.saturating_sub(1)));
    write_audio_http_response(
        &mut stream,
        if partial { 206 } else { 200 },
        "audio/wav",
        &body,
        content_range,
        Some(content_length),
    );
}

fn write_audio_http_response(
    stream: &mut TcpStream,
    status: u16,
    content_type: &str,
    body: &[u8],
    content_range: Option<String>,
    content_length: Option<u64>,
) {
    let reason = match status {
        200 => "OK",
        206 => "Partial Content",
        400 => "Bad Request",
        404 => "Not Found",
        405 => "Method Not Allowed",
        413 => "Payload Too Large",
        416 => "Range Not Satisfiable",
        421 => "Misdirected Request",
        431 => "Request Header Fields Too Large",
        _ => "Internal Server Error",
    };
    let mut headers = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n",
        content_length.unwrap_or(body.len() as u64)
    );
    if content_type == "audio/wav" {
        headers.push_str("Accept-Ranges: bytes\r\n");
    }
    if let Some(content_range) = content_range {
        headers.push_str(&format!("Content-Range: {content_range}\r\n"));
    }
    headers.push_str("Cache-Control: no-store\r\n\r\n");
    if stream.write_all(headers.as_bytes()).is_ok() && !body.is_empty() {
        let _ = stream.write_all(body);
    }
}

fn parse_byte_range(header_value: &str, size: u64) -> Option<(u64, u64)> {
    if size == 0 {
        return None;
    }
    let range = header_value.strip_prefix("bytes=")?;
    if range.contains(',') {
        return None;
    }
    let (start_text, end_text) = range.split_once('-')?;
    if start_text.is_empty() {
        let suffix_length = end_text.parse::<u64>().ok()?;
        return (suffix_length > 0).then(|| (size.saturating_sub(suffix_length), size));
    }
    let start = start_text.parse::<u64>().ok()?;
    if start >= size {
        return None;
    }
    let end = if end_text.is_empty() {
        size - 1
    } else {
        end_text.parse::<u64>().ok()?.min(size - 1)
    };
    (end >= start).then_some((start, end + 1))
}

fn parse_audio_route<'a>(path: &'a str, token: &str) -> Result<(&'a str, usize), u16> {
    if path.contains('?') {
        return Err(404);
    }
    let Some(path) = path.strip_prefix('/') else {
        return Err(404);
    };
    let parts: Vec<_> = path.split('/').collect();
    if parts.len() != 4 || parts[0] != "v1" || parts[1] != token {
        return Err(404);
    }
    if validate_hash(parts[2]).is_err() {
        return Err(404);
    }
    let index = parts[3].parse::<usize>().map_err(|_| 404_u16)?;
    Ok((parts[2], index))
}

fn validate_progress_shape(progress: &Progress) -> Result<(), String> {
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

fn stop_worker_tree(child: &mut Child) -> Result<(), String> {
    #[cfg(unix)]
    {
        let process_group = -(child.id() as i32);
        if child
            .try_wait()
            .map_err(|error| format!("Could not inspect the speech worker: {error}"))?
            .is_some()
        {
            unsafe {
                libc::kill(process_group, libc::SIGKILL);
            }
            return Ok(());
        }
        // The Python process starts Piper in this same process group. Signal
        // both, allow short cleanup, then kill any inference process remaining.
        unsafe {
            libc::kill(process_group, libc::SIGTERM);
        }
        let mut exited = false;
        for _ in 0..20 {
            match child.try_wait() {
                Ok(Some(_)) => {
                    exited = true;
                    break;
                }
                Ok(None) => thread::sleep(Duration::from_millis(25)),
                Err(error) => return Err(format!("Could not stop the speech worker: {error}")),
            }
        }
        unsafe {
            libc::kill(process_group, libc::SIGKILL);
        }
        if !exited {
            child
                .wait()
                .map_err(|error| format!("Could not reap the speech worker: {error}"))?;
        }
        Ok(())
    }
    #[cfg(not(unix))]
    {
        child
            .kill()
            .map_err(|error| format!("Could not stop the speech worker: {error}"))?;
        child
            .wait()
            .map_err(|error| format!("Could not reap the speech worker: {error}"))?;
        Ok(())
    }
}

pub fn run() {
    tauri::Builder::default()
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            pick_document,
            preview_narration,
            current_session,
            start_reading,
            cancel_reading,
            load_progress,
            save_progress,
            list_voices,
            llm_test_connection,
            llm_chat,
            llm_summarize,
            llm_enhance_script,
            get_document_text
        ])
        .setup(|app| {
            let audio_server = AudioServer::start(app.handle().clone())?;
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
    fn local_audio_route_requires_token_and_valid_document_path() {
        let token = "a".repeat(64);
        let hash = "b".repeat(64);
        assert_eq!(
            parse_audio_route(&format!("/v1/{token}/{hash}/3"), &token),
            Ok((hash.as_str(), 3))
        );
        assert!(parse_audio_route(&format!("/v1/wrong/{hash}/3"), &token).is_err());
        assert!(parse_audio_route(&format!("/v1/{token}/../3"), &token).is_err());
        assert!(
            parse_audio_route(&format!("/v1/{token}/{hash}/3?file=/etc/passwd"), &token).is_err()
        );
    }

    #[test]
    fn local_audio_ranges_cover_open_ended_and_suffix_requests() {
        assert_eq!(parse_byte_range("bytes=10-19", 100), Some((10, 20)));
        assert_eq!(parse_byte_range("bytes=90-", 100), Some((90, 100)));
        assert_eq!(parse_byte_range("bytes=-5", 100), Some((95, 100)));
        assert_eq!(parse_byte_range("bytes=100-", 100), None);
        assert_eq!(parse_byte_range("bytes=1-2,4-5", 100), None);
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

    #[test]
    fn log_tail_extracts_explicit_error_even_from_large_review_logs() {
        let root = std::env::temp_dir().join(format!("sonara-log-test-{}", make_job_id()));
        fs::create_dir_all(&root).unwrap();
        let log_file = root.join("worker.log");

        // Simulate 200 lines of review warnings followed by the actual error
        let mut contents = String::new();
        for i in 1..=200 {
            contents.push_str(&format!(
                "sonara: review: Text regions share vertical space (page {i})\n"
            ));
        }
        contents.push_str("sonara: Piper synthesis failed: model buffer overflow\n");
        fs::write(&log_file, &contents).unwrap();

        let msg = worker_failure_message(&log_file, Some(2));
        assert!(msg.contains("sonara: Piper synthesis failed: model buffer overflow"));
        assert!(!msg.contains("worker exit code 2"));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn voice_discovery_identifies_installed_models() {
        let root = std::env::temp_dir().join(format!("sonara-voices-test-{}", make_job_id()));
        fs::create_dir_all(&root).unwrap();

        // Create mock voice files
        fs::write(root.join("en_US-ryan-medium.onnx"), b"onnx").unwrap();
        fs::write(
            root.join("en_US-ryan-medium.onnx.json"),
            br#"{"audio":{"quality":"medium"},"language":{"code":"en_US"}}"#,
        )
        .unwrap();
        fs::write(root.join("en_US-lessac-medium.onnx"), b"onnx").unwrap();
        fs::write(
            root.join("en_US-lessac-medium.onnx.json"),
            br#"{"audio":{"quality":"medium"},"language":{"code":"en_US"}}"#,
        )
        .unwrap();

        let voices = discover_voices(&root).unwrap();
        assert_eq!(voices.len(), 2);
        assert_eq!(voices[0].id, "en_US-ryan-medium");
        assert!(voices[0].is_default);
        assert_eq!(voices[1].id, "en_US-lessac-medium");
        assert!(!voices[1].is_default);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn llm_rpc_test_connection_offline_returns_error() {
        let config = LlmConfigInput {
            provider: "ollama".to_string(),
            endpoint: Some("http://127.0.0.1:59998/v1".to_string()),
            model: Some("llama3.2".to_string()),
            api_key: None,
            temperature: Some(0.7),
            max_tokens: Some(100),
        };
        let result =
            llm_test_connection(config).expect("IPC invocation should return a structured result");
        assert!(!result.ok);
        assert!(result.error.is_some());
    }
}

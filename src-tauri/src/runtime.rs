//! Locating the Python runtime and tools, and starting and stopping worker processes.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
#[cfg(unix)]
use std::os::unix::process::CommandExt;
#[cfg(windows)]
use std::os::windows::process::CommandExt as WindowsCommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use tauri::{AppHandle, Manager};

pub(crate) const MAX_ERROR_LOG_BYTES: u64 = 16 * 1024;

#[derive(Clone, Debug)]
pub(crate) struct RuntimePaths {
    pub(crate) project_root: PathBuf,
    pub(crate) python: PathBuf,
    pub(crate) kokoro_python: PathBuf,
    pub(crate) script: PathBuf,
    pub(crate) llm_script: PathBuf,
    pub(crate) model_dir: PathBuf,
    pub(crate) kokoro_dir: PathBuf,
    pub(crate) tools_dir: PathBuf,
    pub(crate) packaged: bool,
}

/// Validated narration settings passed to the synthesis worker.
pub(crate) struct WorkerOptions<'a> {
    pub(crate) voice: &'a str,
    pub(crate) variation: &'a str,
    pub(crate) engine: &'a str,
    pub(crate) resource_profile: &'a str,
    pub(crate) expand_dates: bool,
    pub(crate) expand_citations: bool,
}

pub(crate) fn spawn_sonara_worker(
    runtime: &RuntimePaths,
    document: &Path,
    output_dir: &Path,
    options: &WorkerOptions<'_>,
    stdout: File,
    stderr: File,
) -> std::io::Result<Child> {
    let python = if options.engine == "kokoro" {
        if !runtime.kokoro_python.is_file() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                format!("Kokoro Python environment is missing at {}. Install its dependencies in that environment.", runtime.kokoro_python.display()),
            ));
        }
        &runtime.kokoro_python
    } else {
        &runtime.python
    };
    let mut command = Command::new(python);
    command
        .env_clear()
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
        .arg(options.voice)
        .arg("--variation")
        .arg(options.variation)
        .arg("--engine")
        .arg(options.engine)
        .arg("--resource-profile")
        .arg(options.resource_profile)
        .arg("--data-dir")
        .arg(&runtime.model_dir)
        .arg("--kokoro-dir")
        .arg(&runtime.kokoro_dir)
        .arg("--output-dir")
        .arg(output_dir)
        .args(pdf_tool_args(runtime))
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .env("PYTHONUNBUFFERED", "1");
    configure_runtime_command(&mut command, runtime);
    if options.expand_dates {
        command.arg("--expand-dates");
    }
    if options.expand_citations {
        command.arg("--expand-citations");
    }
    #[cfg(unix)]
    command.process_group(0);
    command.spawn()
}

pub(crate) fn resolve_runtime(app: Option<&AppHandle>) -> Result<RuntimePaths, String> {
    let data_root = if let Some(app) = app {
        app.path()
            .app_local_data_dir()
            .map_err(|error| format!("Could not locate Sonara's user data directory: {error}"))?
    } else {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.sonara-test-data")
    };

    let explicit_root = std::env::var_os("SONARA_PROJECT_ROOT").map(PathBuf::from);
    let (root, packaged) = if let Some(root) = explicit_root {
        (root, false)
    } else if cfg!(debug_assertions) {
        (PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(".."), false)
    } else if let Some(app) = app {
        let resources = app
            .path()
            .resource_dir()
            .map_err(|error| format!("Could not locate Sonara's installed resources: {error}"))?;
        (resources.join("sonara"), true)
    } else {
        return Err("Installed Sonara resources are unavailable.".to_owned());
    };

    let mut runtime = resolve_runtime_layout(&root, &data_root, packaged, cfg!(windows))?;
    if let Some(python) = std::env::var_os("SONARA_PYTHON") {
        runtime.python = resolve_override_path(&runtime.project_root, PathBuf::from(python));
        if packaged {
            runtime.kokoro_python = runtime.python.clone();
        }
    }
    if let Some(kokoro_python) = std::env::var_os("SONARA_KOKORO_PYTHON") {
        runtime.kokoro_python =
            resolve_override_path(&runtime.project_root, PathBuf::from(kokoro_python));
    }
    if let Some(model_dir) = std::env::var_os("SONARA_MODEL_DIR") {
        runtime.model_dir = resolve_override_path(&runtime.project_root, PathBuf::from(model_dir));
    }
    Ok(runtime)
}

pub(crate) fn resolve_runtime_layout(
    root: &Path,
    data_root: &Path,
    packaged: bool,
    windows: bool,
) -> Result<RuntimePaths, String> {
    let root = root
        .canonicalize()
        .map_err(|error| format!("Could not locate Sonara runtime resources: {error}"))?;
    let script = root.join("sonara.py");
    let llm_script = root.join("llm_client.py");
    if !script.is_file() || !llm_script.is_file() {
        return Err(format!(
            "Sonara backend resources are incomplete in {}.",
            root.display()
        ));
    }

    let python = if packaged {
        root.join(if windows {
            "sonara-runtime.exe"
        } else {
            "sonara-runtime"
        })
    } else if windows {
        root.join(".venv/Scripts/python.exe")
    } else {
        root.join(".venv/bin/python")
    };
    if !python.is_file() {
        return Err(if packaged {
            format!("Bundled Sonara runtime is missing: {}", python.display())
        } else {
            format!("Python environment was not found at {}. Set SONARA_PYTHON to the environment's Python executable.", python.display())
        });
    }

    let data_root = if packaged {
        data_root.to_path_buf()
    } else {
        root.clone()
    };
    let model_dir = data_root.join("models/piper");
    let kokoro_dir = data_root.join("models/kokoro");
    let kokoro_python = if packaged {
        python.clone()
    } else if windows {
        root.join(".cache/kokoro-venv/Scripts/python.exe")
    } else {
        root.join(".cache/kokoro-venv/bin/python")
    };

    Ok(RuntimePaths {
        project_root: root.clone(),
        python,
        kokoro_python,
        script,
        llm_script,
        model_dir,
        kokoro_dir,
        tools_dir: root.join("tools"),
        packaged,
    })
}

pub(crate) fn resolve_override_path(root: &Path, path: PathBuf) -> PathBuf {
    if path.is_absolute() {
        path
    } else {
        root.join(path)
    }
}

pub(crate) fn runtime_search_path(runtime: &RuntimePaths) -> std::ffi::OsString {
    let existing = std::env::var_os("PATH").unwrap_or_default();
    let mut paths = vec![runtime.tools_dir.join("bin"), runtime.tools_dir.clone()];
    paths.extend(std::env::split_paths(&existing));
    std::env::join_paths(paths).unwrap_or(existing)
}

pub(crate) fn pdftotext_path(runtime: &RuntimePaths) -> PathBuf {
    let executable = if cfg!(windows) {
        "pdftotext.exe"
    } else {
        "pdftotext"
    };
    let nested = runtime.tools_dir.join("bin").join(executable);
    if nested.is_file() {
        nested
    } else {
        runtime.tools_dir.join(executable)
    }
}

pub(crate) fn pdf_tool_args(runtime: &RuntimePaths) -> Vec<std::ffi::OsString> {
    if runtime.packaged {
        vec![
            "--pdftotext".into(),
            pdftotext_path(runtime).into_os_string(),
        ]
    } else {
        Vec::new()
    }
}

pub(crate) fn configure_runtime_command(command: &mut Command, runtime: &RuntimePaths) {
    command.env("PATH", runtime_search_path(runtime));
    if runtime.packaged {
        command.env("TESSDATA_PREFIX", runtime.tools_dir.join("tessdata"));
        command.env("POPPLER_DATADIR", runtime.tools_dir.join("share/poppler"));
        #[cfg(target_os = "linux")]
        {
            let existing = std::env::var_os("LD_LIBRARY_PATH").unwrap_or_default();
            let paths = std::iter::once(runtime.tools_dir.join("lib"))
                .chain(std::env::split_paths(&existing))
                .collect::<Vec<_>>();
            if let Ok(joined) = std::env::join_paths(paths) {
                command.env("LD_LIBRARY_PATH", joined);
            }
        }
    }
    #[cfg(windows)]
    {
        for name in [
            "SystemRoot",
            "WINDIR",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
        ] {
            if let Some(value) = std::env::var_os(name) {
                command.env(name, value);
            }
        }
        if let Some(profile) = std::env::var_os("USERPROFILE") {
            command.env("HOME", profile);
        }
        command.creation_flags(0x0800_0000);
    }
}

pub(crate) fn verify_installed_runtime(app: &AppHandle) -> Result<(), String> {
    let runtime = resolve_runtime(Some(app))?;
    if !runtime.packaged {
        return Err("Installed-runtime check did not resolve packaged resources.".to_owned());
    }
    let mut runtime_command = Command::new(&runtime.python);
    runtime_command.arg("--self-check");
    configure_runtime_command(&mut runtime_command, &runtime);
    let runtime_output = runtime_command
        .output()
        .map_err(|error| format!("Could not start the bundled inference runtime: {error}"))?;
    if !runtime_output.status.success() {
        return Err(format!(
            "Bundled inference runtime failed its self-check: {}",
            String::from_utf8_lossy(&runtime_output.stderr).trim()
        ));
    }
    let report: serde_json::Value =
        serde_json::from_slice(&runtime_output.stdout).map_err(|error| {
            format!("Bundled inference runtime returned invalid status JSON: {error}")
        })?;
    if report.get("ok").and_then(serde_json::Value::as_bool) != Some(true) {
        return Err(format!(
            "Bundled inference runtime reports unavailable engines: {report}"
        ));
    }

    for (name, executable, args) in [
        ("pdftotext", pdftotext_path(&runtime), vec!["-v"]),
        (
            "pdftoppm",
            runtime.tools_dir.join("bin").join(if cfg!(windows) {
                "pdftoppm.exe"
            } else {
                "pdftoppm"
            }),
            vec!["-v"],
        ),
    ] {
        let mut command = Command::new(executable);
        command.args(args);
        configure_runtime_command(&mut command, &runtime);
        let output = command
            .output()
            .map_err(|error| format!("Could not run bundled {name}: {error}"))?;
        if !output.status.success() {
            return Err(format!("Bundled {name} failed its startup check."));
        }
    }

    let mut tesseract = Command::new(runtime.tools_dir.join("bin").join(if cfg!(windows) {
        "tesseract.exe"
    } else {
        "tesseract"
    }));
    tesseract.arg("--list-langs");
    configure_runtime_command(&mut tesseract, &runtime);
    let output = tesseract
        .output()
        .map_err(|error| format!("Could not run bundled Tesseract: {error}"))?;
    if !output.status.success()
        || !String::from_utf8_lossy(&output.stdout)
            .lines()
            .any(|line| line.trim() == "eng")
    {
        return Err(
            "Bundled Tesseract or its English language data failed the startup check.".to_owned(),
        );
    }
    Ok(())
}

pub(crate) fn stop_worker_tree(child: &mut Child) -> Result<(), String> {
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
                Ok(None) => std::thread::sleep(std::time::Duration::from_millis(25)),
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

pub(crate) fn read_log_tail(path: &Path, max_bytes: u64) -> Option<String> {
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

pub(crate) fn extract_error_summary(detail: &str, limit: usize) -> String {
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

pub(crate) fn worker_failure_message(log_path: &Path, exit_code: Option<i32>) -> String {
    let detail = read_log_tail(log_path, MAX_ERROR_LOG_BYTES);
    match detail {
        Some(detail) => format!("Speech generation failed: {}", extract_error_summary(&detail, 4000)),
        None => format!("Speech generation failed (worker exit code {}). Check the local Python and Piper setup.", exit_code.map_or_else(|| "unknown".to_owned(), |code| code.to_string())),
    }
}

pub(crate) fn truncate_chars(value: &str, limit: usize) -> String {
    let mut chars = value.chars();
    let prefix: String = chars.by_ref().take(limit).collect();
    if chars.next().is_some() {
        format!("{prefix}…")
    } else {
        prefix
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::make_job_id;
    use std::fs;

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
    fn packaged_runtime_uses_installed_resources_and_user_data() {
        let base = std::env::temp_dir().join(format!("sonara-runtime-paths-{}", make_job_id()));
        let resource_root = base.join("Program Files/Sonara/resources/sonara");
        let user_data = base.join("User Data/Sonara");
        fs::create_dir_all(&resource_root).unwrap();
        fs::create_dir_all(&user_data).unwrap();
        fs::write(resource_root.join("sonara.py"), b"backend entry").unwrap();
        fs::write(resource_root.join("llm_client.py"), b"llm entry").unwrap();
        fs::write(resource_root.join("sonara-runtime"), b"runtime").unwrap();

        let runtime = resolve_runtime_layout(&resource_root, &user_data, true, false).unwrap();
        assert_eq!(runtime.project_root, resource_root.canonicalize().unwrap());
        assert_eq!(runtime.python, runtime.project_root.join("sonara-runtime"));
        assert_eq!(runtime.model_dir, user_data.join("models/piper"));
        assert_eq!(runtime.kokoro_dir, user_data.join("models/kokoro"));
        assert_eq!(runtime.tools_dir, runtime.project_root.join("tools"));
        fs::create_dir_all(runtime.tools_dir.join("bin")).unwrap();
        fs::write(runtime.tools_dir.join("bin/pdftotext"), b"poppler").unwrap();
        assert_eq!(
            pdftotext_path(&runtime),
            runtime.tools_dir.join("bin/pdftotext")
        );
        assert_eq!(pdf_tool_args(&runtime).len(), 2);
        assert_eq!(
            PathBuf::from(&pdf_tool_args(&runtime)[1]),
            runtime.tools_dir.join("bin/pdftotext")
        );
        assert!(!runtime.model_dir.starts_with(&runtime.project_root));

        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn packaged_runtime_selects_windows_executable_name() {
        let base = std::env::temp_dir().join(format!("sonara-runtime-windows-{}", make_job_id()));
        let resource_root = base.join("resources/sonara");
        fs::create_dir_all(&resource_root).unwrap();
        fs::write(resource_root.join("sonara.py"), b"backend entry").unwrap();
        fs::write(resource_root.join("llm_client.py"), b"llm entry").unwrap();
        fs::write(resource_root.join("sonara-runtime.exe"), b"runtime").unwrap();

        let runtime =
            resolve_runtime_layout(&resource_root, &base.join("data"), true, true).unwrap();
        assert_eq!(
            runtime.python,
            runtime.project_root.join("sonara-runtime.exe")
        );
        assert_eq!(runtime.kokoro_python, runtime.python);

        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn packaged_runtime_reports_missing_files_without_falling_back_to_source_checkout() {
        let base = std::env::temp_dir().join(format!("sonara-runtime-missing-{}", make_job_id()));
        fs::create_dir_all(&base).unwrap();
        let error = resolve_runtime_layout(&base, &base.join("data"), true, false)
            .expect_err("an empty install resource directory is not a runtime");
        assert!(error.contains("backend resources are incomplete"));
        let _ = fs::remove_dir_all(base);
    }
}

//! Native file pickers. Each platform runs a fixed script through a system tool; no
//! user input is interpolated into it.

use std::path::PathBuf;
use std::process::{Command, Stdio};

#[cfg(target_os = "linux")]
pub(crate) fn choose_document_path() -> Result<Option<PathBuf>, String> {
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
pub(crate) fn choose_document_path() -> Result<Option<PathBuf>, String> {
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
pub(crate) fn choose_document_path() -> Result<Option<PathBuf>, String> {
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
pub(crate) fn choose_document_path() -> Result<Option<PathBuf>, String> {
    Err("File selection is not supported on this operating system.".to_owned())
}

#[cfg(target_os = "linux")]
pub(crate) fn choose_gguf_path() -> Result<Option<PathBuf>, String> {
    let output = match Command::new("zenity")
        .arg("--file-selection")
        .arg("--title=Choose a GGUF model for Sonara")
        .arg("--file-filter=GGUF Models | *.gguf")
        .arg("--file-filter=All Files | *")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
    {
        Ok(output) => output,
        Err(_) => Command::new("kdialog")
            .arg("--getopenfilename")
            .arg(".")
            .arg("*.gguf|GGUF models\n*|All files (*)")
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .output()
            .map_err(|error| format!("Could not open the model picker: {error}"))?,
    };
    if !output.status.success() {
        return Ok(None);
    }
    let value = String::from_utf8(output.stdout)
        .map_err(|_| "The model picker returned an invalid path.".to_owned())?;
    let value = value.trim();
    if value.is_empty() {
        Ok(None)
    } else {
        Ok(Some(PathBuf::from(value)))
    }
}

#[cfg(target_os = "macos")]
pub(crate) fn choose_gguf_path() -> Result<Option<PathBuf>, String> {
    let output = Command::new("osascript").arg("-e")
        .arg(r#"POSIX path of (choose file with prompt "Choose a GGUF model for Sonara" of type {"gguf"})"#)
        .stdout(Stdio::piped()).stderr(Stdio::null()).output()
        .map_err(|error| format!("Could not open macOS model picker: {error}"))?;
    if !output.status.success() {
        return Ok(None);
    }
    let value = String::from_utf8(output.stdout)
        .map_err(|_| "The model picker returned an invalid path.".to_owned())?;
    let value = value.trim();
    if value.is_empty() {
        Ok(None)
    } else {
        Ok(Some(PathBuf::from(value)))
    }
}

#[cfg(target_os = "windows")]
pub(crate) fn choose_gguf_path() -> Result<Option<PathBuf>, String> {
    let script = r#"Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Filter = "GGUF models (*.gguf)|*.gguf|All files (*.*)|*.*"
$dialog.Title = "Choose a GGUF model for Sonara"
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dialog.FileName }"#;
    let output = Command::new("powershell")
        .arg("-NoProfile")
        .arg("-Command")
        .arg(script)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .map_err(|error| format!("Could not open Windows model picker: {error}"))?;
    if !output.status.success() {
        return Ok(None);
    }
    let value = String::from_utf8(output.stdout)
        .map_err(|_| "The model picker returned an invalid path.".to_owned())?;
    let value = value.trim();
    if value.is_empty() {
        Ok(None)
    } else {
        Ok(Some(PathBuf::from(value)))
    }
}

#[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
pub(crate) fn choose_gguf_path() -> Result<Option<PathBuf>, String> {
    Err("Model file selection is not supported on this operating system.".to_owned())
}

/// Pick a program, such as llama.cpp's `llama-server`.
#[cfg(target_os = "linux")]
pub(crate) fn choose_executable_path(title: &str) -> Result<Option<PathBuf>, String> {
    let output = match Command::new("zenity")
        .arg("--file-selection")
        .arg(format!("--title={title}"))
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
    {
        Ok(output) => output,
        Err(_) => Command::new("kdialog")
            .arg("--getopenfilename")
            .arg(".")
            .arg("*|All files (*)")
            .arg("--title")
            .arg(title)
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .output()
            .map_err(|error| format!("Could not open the file picker: {error}"))?,
    };
    picked_path(output)
}

#[cfg(target_os = "macos")]
pub(crate) fn choose_executable_path(title: &str) -> Result<Option<PathBuf>, String> {
    let script = format!(
        r#"POSIX path of (choose file with prompt "{}")"#,
        title.replace('"', "")
    );
    let output = Command::new("osascript")
        .arg("-e")
        .arg(script)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .map_err(|error| format!("Could not open the macOS file picker: {error}"))?;
    picked_path(output)
}

#[cfg(target_os = "windows")]
pub(crate) fn choose_executable_path(title: &str) -> Result<Option<PathBuf>, String> {
    let script = format!(
        r#"Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Filter = "Programs (*.exe)|*.exe|All files (*.*)|*.*"
$dialog.Title = "{}"
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{ Write-Output $dialog.FileName }}"#,
        title.replace('"', "")
    );
    let output = Command::new("powershell")
        .arg("-NoProfile")
        .arg("-Command")
        .arg(script)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .map_err(|error| format!("Could not open the Windows file picker: {error}"))?;
    picked_path(output)
}

#[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
pub(crate) fn choose_executable_path(_title: &str) -> Result<Option<PathBuf>, String> {
    Err("File selection is not supported on this operating system.".to_owned())
}

#[cfg(any(target_os = "linux", target_os = "macos", target_os = "windows"))]
fn picked_path(output: std::process::Output) -> Result<Option<PathBuf>, String> {
    if !output.status.success() {
        return Ok(None);
    }
    let value = String::from_utf8(output.stdout)
        .map_err(|_| "The file picker returned an invalid path.".to_owned())?;
    let value = value.trim();
    Ok((!value.is_empty()).then(|| PathBuf::from(value)))
}

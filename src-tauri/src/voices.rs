//! Discovery of installed Piper voices and their display metadata.

use serde::{Deserialize, Serialize};
use std::fs::{self};
use std::path::Path;

pub(crate) const DEFAULT_FALLBACK_VOICE: &str = "en_US-ryan-medium";

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct VoiceInfo {
    pub id: String,
    pub name: String,
    pub quality: String,
    pub language: String,
    pub is_default: bool,
}

pub(crate) fn discover_voices(model_dir: &Path) -> Result<Vec<VoiceInfo>, String> {
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

pub(crate) fn voice_priority(id: &str) -> usize {
    match id {
        "en_US-ryan-medium" => 0,
        "en_US-lessac-medium" => 1,
        "en_US-bryce-medium" => 2,
        "en_US-john-medium" => 3,
        _ => 10,
    }
}

pub(crate) fn parse_voice_metadata(json_path: &Path, id: &str) -> (String, String, String) {
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::make_job_id;

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
}

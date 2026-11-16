//! Discovery of installed Piper voices and their display metadata.

use serde::{Deserialize, Serialize};
use std::fs::{self};
use std::path::Path;

pub(crate) const DEFAULT_FALLBACK_VOICE: &str = "en_US-ryan-medium";
pub(crate) const DEFAULT_KOKORO_VOICE: &str = "af_sarah";

/// Kokoro v1.0 voices Sonara offers. The first letter is the language and
/// must match `KOKORO_LANGUAGES` in tts_engine.py; the second is f/m.
/// Japanese voices are left out: they need a G2P that Sonara does not ship.
const KOKORO_VOICES: &[&str] = &[
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_heart",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
    "ef_dora",
    "em_alex",
    "em_santa",
    "ff_siwis",
    "hf_alpha",
    "hf_beta",
    "hm_omega",
    "hm_psi",
    "if_sara",
    "im_nicola",
    "pf_dora",
    "pm_alex",
    "pm_santa",
    "zf_xiaobei",
    "zf_xiaoni",
    "zf_xiaoxiao",
    "zf_xiaoyi",
    "zm_yunjian",
    "zm_yunxi",
    "zm_yunxia",
    "zm_yunyang",
];

fn kokoro_language_label(prefix: u8) -> Option<&'static str> {
    Some(match prefix {
        b'a' => "US English",
        b'b' => "British English",
        b'e' => "Spanish",
        b'f' => "French",
        b'h' => "Hindi",
        b'i' => "Italian",
        b'p' => "Brazilian Portuguese",
        b'z' => "Mandarin Chinese (experimental)",
        _ => return None,
    })
}

pub(crate) fn is_kokoro_voice(voice: &str) -> bool {
    KOKORO_VOICES.contains(&voice)
}

/// The Kokoro voice list for Settings, grouped by language.
pub(crate) fn kokoro_voices() -> Vec<VoiceInfo> {
    KOKORO_VOICES
        .iter()
        .filter_map(|id| {
            let bytes = id.as_bytes();
            let language = kokoro_language_label(bytes[0])?;
            let gender = if bytes[1] == b'f' { "female" } else { "male" };
            let raw = &id[3..];
            let name = raw[..1].to_uppercase() + &raw[1..];
            Some(VoiceInfo {
                id: (*id).to_owned(),
                name: format!("{name} · {language} · {gender}"),
                quality: "Kokoro".to_owned(),
                language: language.to_owned(),
                is_default: *id == DEFAULT_KOKORO_VOICE,
            })
        })
        .collect()
}

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
    fn kokoro_voices_have_languages_and_one_default() {
        let voices = kokoro_voices();
        assert_eq!(voices.len(), KOKORO_VOICES.len());
        assert_eq!(voices.iter().filter(|voice| voice.is_default).count(), 1);
        let george = voices.iter().find(|voice| voice.id == "bm_george").unwrap();
        assert_eq!(george.name, "George · British English · male");
        assert!(is_kokoro_voice("ff_siwis"));
        assert!(!is_kokoro_voice("jf_alpha"));
        assert!(!is_kokoro_voice("en_US-ryan-medium"));
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
}

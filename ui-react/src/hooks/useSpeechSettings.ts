import { useCallback, useEffect, useState } from "react";
import {
  type PiperVariation,
  type ResourceProfile,
  type SpeechEngine,
  type VoiceInfo,
  listKokoroVoices,
  listVoices,
} from "../lib/tauri";

export const DEFAULT_PIPER_VOICE = "en_US-ryan-medium";
export const DEFAULT_KOKORO_VOICE = "af_sarah";

const KEYS = {
  engine: "sonara_speech_engine",
  profile: "sonara_resource_profile",
  voice: "sonara_selected_voice",
  variation: "sonara_piper_variation",
  expandDates: "sonara_expand_dates",
  expandCitations: "sonara_expand_citations",
} as const;

// Storage can be unavailable in restricted WebViews; settings then last only
// for the session.
function readSetting(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeSetting(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}

/** Kokoro IDs are a language letter, f/m, then a name: af_sarah, ff_siwis. */
export function isKokoroVoice(voice: string | null | undefined): boolean {
  return /^[a-z][fm]_[a-z]+$/.test(voice ?? "");
}

function initialVoice(): string {
  const selected = readSetting(KEYS.voice);
  if (readSetting(KEYS.engine) === "kokoro") {
    return isKokoroVoice(selected) ? selected! : DEFAULT_KOKORO_VOICE;
  }
  return selected && !isKokoroVoice(selected) ? selected : DEFAULT_PIPER_VOICE;
}

/** Voice, engine and narration options, persisted per device. */
export function useSpeechSettings(tauriAvailable: boolean) {
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [kokoroVoices, setKokoroVoices] = useState<VoiceInfo[]>([]);
  const [speechEngine, setSpeechEngineState] = useState<SpeechEngine>(() =>
    readSetting(KEYS.engine) === "kokoro" ? "kokoro" : "piper",
  );
  const [resourceProfile, setResourceProfileState] = useState<ResourceProfile>(() => {
    const value = readSetting(KEYS.profile);
    return value === "low_resource" || value === "high_performance" ? value : "standard";
  });
  const [selectedVoice, setSelectedVoiceState] = useState<string>(initialVoice);
  const [piperVariation, setPiperVariationState] = useState<PiperVariation>(() => {
    const value = readSetting(KEYS.variation);
    return value === "less" || value === "more" ? value : "voice_default";
  });
  const [expandDates, setExpandDatesState] = useState(() => readSetting(KEYS.expandDates) === "true");
  const [expandCitations, setExpandCitationsState] = useState(
    () => readSetting(KEYS.expandCitations) === "true",
  );

  const setSelectedVoice = useCallback((voiceId: string) => {
    setSelectedVoiceState(voiceId);
    writeSetting(KEYS.voice, voiceId);
  }, []);

  const setSpeechEngine = useCallback((value: SpeechEngine) => {
    setSpeechEngineState(value);
    writeSetting(KEYS.engine, value);
    setSelectedVoice(value === "kokoro" ? DEFAULT_KOKORO_VOICE : DEFAULT_PIPER_VOICE);
  }, [setSelectedVoice]);

  const setResourceProfile = useCallback((value: ResourceProfile) => {
    setResourceProfileState(value);
    writeSetting(KEYS.profile, value);
  }, []);

  const setPiperVariation = useCallback((value: PiperVariation) => {
    setPiperVariationState(value);
    writeSetting(KEYS.variation, value);
  }, []);

  const setExpandDates = useCallback((enabled: boolean) => {
    setExpandDatesState(enabled);
    writeSetting(KEYS.expandDates, String(enabled));
  }, []);

  const setExpandCitations = useCallback((enabled: boolean) => {
    setExpandCitationsState(enabled);
    writeSetting(KEYS.expandCitations, String(enabled));
  }, []);

  useEffect(() => {
    if (!tauriAvailable) return;
    let cancelled = false;
    void listVoices()
      .then((available) => {
        if (cancelled) return;
        setVoices(available);
        const saved = readSetting(KEYS.voice);
        // A saved Kokoro voice is checked against the Kokoro list instead.
        if (isKokoroVoice(saved) && readSetting(KEYS.engine) === "kokoro") return;
        if (!saved || !available.some((voice) => voice.id === saved)) {
          // Fall back without persisting, so a voice installed later is still
          // picked up from the stored choice.
          setSelectedVoiceState(
            available.find((voice) => voice.isDefault)?.id || available[0]?.id || DEFAULT_PIPER_VOICE,
          );
        }
      })
      .catch(() => {
        /* voices unavailable */
      });
    void listKokoroVoices()
      .then((available) => {
        if (cancelled || !Array.isArray(available)) return;
        setKokoroVoices(available);
        const saved = readSetting(KEYS.voice);
        if (readSetting(KEYS.engine) === "kokoro" && !available.some((voice) => voice.id === saved)) {
          setSelectedVoiceState(DEFAULT_KOKORO_VOICE);
        }
      })
      .catch(() => {
        /* Kokoro list unavailable */
      });
    return () => {
      cancelled = true;
    };
  }, [tauriAvailable]);

  return {
    voices,
    kokoroVoices,
    speechEngine,
    setSpeechEngine,
    resourceProfile,
    setResourceProfile,
    selectedVoice,
    setSelectedVoice,
    piperVariation,
    setPiperVariation,
    expandDates,
    setExpandDates,
    expandCitations,
    setExpandCitations,
    selectedVoiceName: [...voices, ...kokoroVoices].find((voice) => voice.id === selectedVoice)?.name ?? selectedVoice,
  };
}

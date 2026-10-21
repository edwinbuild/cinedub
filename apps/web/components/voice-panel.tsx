"use client";

import type { Speaker, VoiceChoice, VoiceProfile } from "@cinedub/contracts";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { StockVariationField } from "./stock-variation-field";

export function VoicePanel({ speakers, profiles, provider, disabled, onSaved }: {
  speakers: Speaker[]; profiles: VoiceProfile[]; provider: "fake" | "sarvam"; disabled: boolean;
  onSaved: () => void;
}) {
  const [voices, setVoices] = useState<VoiceChoice[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { let active = true;
    api.stockVoices(provider).then((choices) => { if (active) setVoices(choices); })
      .catch(() => { if (active) setError("Could not load the stock voice catalog"); });
    return () => { active = false; };
  }, [provider]);
  async function assign(speakerId: string, voiceId: string, pace: number, variation?: number, baseline?: { id: string; version: number }) {
    const speaker = speakers.find((item) => item.id === speakerId);
    const selected = profiles.find((item) => item.id === speaker?.voice_profile_id);
    try { setBusy(speakerId); setError(null); await api.assignStockVoice(speakerId, {
      provider, voice_id: voiceId, pace, variation: provider === "sarvam" ? variation ?? .6 : undefined,
      expected_profile_id: baseline?.id ?? speaker?.voice_profile_id ?? null, expected_profile_version: baseline?.version ?? selected?.version,
    }); await onSaved(); return true; }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Voice assignment failed"); return false; }
    finally { setBusy(null); }
  }
  return <div className="voiceAssignments"><p className="eyebrow">{provider === "fake" ? "Demo tone assignment" : "Stock Malayalam voices"}</p>
    {provider === "fake" && <p className="lineWarning">Test tones only — no generated speech.</p>}
    {speakers.map((speaker) => {
      const profile = profiles.find((item) => item.speaker_id === speaker.id && item.provider === provider && item.voice_kind === "preset");
      const selected = profile && speaker.voice_profile_id === profile.id;
      return <div className="voiceAssignment" key={speaker.id}>
        <label className="fieldLabel">{speaker.display_name}<select aria-label={`Voice for ${speaker.display_name}`} value={selected ? profile.provider_voice_id ?? "" : ""}
          disabled={disabled || !!busy} onChange={(event) => assign(speaker.id, event.target.value, Number(profile?.settings_json.pace ?? 1), Number(profile?.settings_json.variation ?? .6))}>
          <option value="" disabled>{speaker.voice_profile_id && !selected ? "Clone selected · choose stock to switch" : "Choose a voice"}</option>{voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.display_name}</option>)}</select></label>
        {selected && <label className="fieldLabel">Speaking pace<input aria-label={`Voice pace for ${speaker.display_name}`} type="number" min="0.5" max="2" step="0.05"
          key={`${profile.id}:${profile.version}`} defaultValue={Number(profile.settings_json.pace ?? 1)} disabled={disabled || !!busy}
          onBlur={(event) => { const pace = Number(event.target.value); if (Number.isFinite(pace) && pace >= .5 && pace <= 2 && pace !== profile.settings_json.pace)
            void assign(speaker.id, profile.provider_voice_id!, pace, Number(profile.settings_json.variation ?? .6)); }} /></label>}
        {selected && provider === "sarvam" && <StockVariationField key={profile.id} profile={profile} speakerName={speaker.display_name}
          disabled={disabled || !!busy} onSave={(variation, version) => assign(speaker.id, profile.provider_voice_id!, Number(profile.settings_json.pace ?? 1), variation, { id: profile.id, version })} />}
      </div>;
    })}
    {error && <p className="inlineError" role="alert">{error}</p>}
  </div>;
}

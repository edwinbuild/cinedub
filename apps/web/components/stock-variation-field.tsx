"use client";

import type { VoiceProfile } from "@cinedub/contracts";
import { useState } from "react";

export function StockVariationField({ profile, speakerName, disabled, onSave }: {
  profile: VoiceProfile; speakerName: string; disabled: boolean;
  onSave: (variation: number, expectedVersion: number) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState<{ text: string; version: number } | null>(null);
  const value = draft?.text ?? String(profile.settings_json.variation ?? .6);
  const numeric = Number(value);
  const valid = value.trim() !== "" && Number.isFinite(numeric) && numeric >= .01 && numeric <= 1;
  const conflict = draft !== null && draft.version !== profile.version;
  async function save() {
    if (!draft || !valid || conflict || disabled) return;
    const submitted = draft;
    if (await onSave(numeric, submitted.version)) {
      setDraft((current) => current?.text === submitted.text && current.version === submitted.version ? null : current);
    }
  }
  return <div aria-label={`Generation settings for ${speakerName}`}>
    <label className="fieldLabel">Generation variation (not emotion)
      <input aria-label={`Generation variation for ${speakerName}`} aria-describedby={`variation-help-${profile.id}`}
        type="number" min="0.01" max="1" step="0.01" required value={value} disabled={disabled}
        onChange={(event) => { const text = event.target.value; setDraft((previous) => ({ text, version: previous?.version ?? profile.version })); }} />
    </label>
    <p id={`variation-help-${profile.id}`} className="lineWarning">Manual control; higher values may add variation or artifacts, not a chosen emotion. Saving clears this speaker&apos;s selected takes; text approvals stay unchanged. New takes need listening review. No speech is generated until requested.</p>
    {!valid && <p role="alert" className="inlineError">Enter a number from 0.01 to 1.</p>}
    {conflict && <p role="alert" className="inlineError">Saved voice settings changed. Copy or discard this draft; it cannot overwrite the newer version.</p>}
    <button type="button" disabled={!draft || !valid || conflict || disabled} onClick={() => void save()}>Save generation variation for {speakerName}</button>
    {draft && <button type="button" disabled={disabled} onClick={() => setDraft(null)}>Discard generation variation draft for {speakerName}</button>}
  </div>;
}

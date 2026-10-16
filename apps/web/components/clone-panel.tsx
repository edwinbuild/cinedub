"use client";

import type { ConsentRecord, JobRequest, ProjectDetail, VoiceProfile } from "@cinedub/contracts";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { API_URL, api } from "@/lib/api";

function formChanged(form: HTMLFormElement) {
  return Array.from(form.elements).some((field) => {
    if (field instanceof HTMLInputElement) return field.type === "checkbox"
      ? field.checked !== field.defaultChecked : field.value !== field.defaultValue;
    if (field instanceof HTMLTextAreaElement) return field.value !== field.defaultValue;
    if (field instanceof HTMLSelectElement) return Array.from(field.options).some((option) => option.selected !== option.defaultSelected);
    return false;
  });
}

export function ClonePanel({ project, provider, available, disabled, onSaved, onRun, onDirty }: {
  project: ProjectDetail; provider: "sarvam" | "fake"; available: boolean; disabled: boolean;
  onSaved: () => Promise<void>; onRun: (payload: JobRequest) => Promise<void>;
  onDirty: (dirty: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<Record<string, ConsentRecord[]>>({});
  const [reviewed, setReviewed] = useState<Record<string, boolean>>({});
  const [allowance, setAllowance] = useState("");
  const [dirty, setDirty] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => () => onDirty(false), [onDirty]);
  function markDirty(value: boolean) { setDirty(value); onDirty(value); }
  const clones = project.voice_profiles.filter((profile) => profile.voice_kind === "clone");

  async function action(run: () => Promise<unknown>) {
    try { setBusy(true); setError(null); await run(); await onSaved(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Voice reference action failed"); }
    finally { setBusy(false); }
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    await action(async () => {
      await api.createVoiceProfile(project.id, {
        speaker_id: String(fields.get("speaker")), display_name: String(fields.get("name")), provider,
        reference_asset_id: String(fields.get("source")),
        reference_start_ms: Math.round(Number(fields.get("start")) * 1000),
        reference_end_ms: Math.round(Number(fields.get("end")) * 1000),
        consent: { approved: fields.has("approved"), attested_by: String(fields.get("attested")),
          rights_holder: String(fields.get("holder")), note: String(fields.get("note")),
          allows_provider_upload: fields.has("upload"), clean_single_speaker: fields.has("clean") },
      });
      form.reset();
      markDirty(false);
    });
  }
  async function revoke(profile: VoiceProfile) {
    const who = window.prompt("Who is recording this consent revocation?"); if (!who?.trim()) return;
    if (!window.confirm("Revoke this clone? CineDub will block its reference, candidates and rendered audio. Already downloaded files and provider-stored copies cannot be recalled; deleting the provider copy is a separate action.")) return;
    await action(() => api.revokeVoiceProfile(profile.id, who));
  }

  return <details className="clonePanel"><summary>Voice references &amp; consent <small>{clones.length} saved · {provider === "fake" ? "demo only" : "Sarvam beta"}</small></summary>
    <p>Use a clean 10–15 second recording of one consenting speaker. Saving and preparing are local. Registering uploads the reference to {provider === "fake" ? "the demo adapter (no external service)" : "Sarvam, where it is stored as a saved voice"}.</p>
    <p className="lineWarning">Owning a film file is not actor permission. This records your attestation, not independent legal or identity verification. Original uploads and local history are retained after revocation.</p>
    <form ref={formRef} aria-label="Create consented voice reference" onSubmit={save}
      onChange={(event) => markDirty(formChanged(event.currentTarget))}>
      <div className="cloneFields">
        <label>Speaker<select name="speaker" aria-label="Reference speaker" required disabled={disabled || busy} defaultValue="">
          <option value="" disabled>Choose speaker</option>{project.speakers.map((speaker) => <option key={speaker.id} value={speaker.id}>{speaker.display_name}</option>)}</select></label>
        <label>Reference name<input name="name" aria-label="Reference name" maxLength={100} required disabled={disabled || busy} /></label>
        <label>Source recording<select name="source" aria-label="Reference source" required disabled={disabled || busy} defaultValue="">
          <option value="" disabled>Choose imported recording</option>{project.assets.filter((asset) => Number(asset.duration_ms) >= 10000).map((asset) => <option key={asset.id} value={asset.id}>{asset.filename}</option>)}</select></label>
        <label>Start (s)<input name="start" aria-label="Reference start seconds" type="number" min="0" step="0.001" defaultValue="0" required disabled={disabled || busy} /></label>
        <label>End (s)<input name="end" aria-label="Reference end seconds" type="number" min="10" step="0.001" defaultValue="10" required disabled={disabled || busy} /></label>
        <label>Rights holder<input name="holder" aria-label="Voice rights holder" maxLength={120} required disabled={disabled || busy} /></label>
        <label>Attested by<input name="attested" aria-label="Consent attested by" maxLength={120} required disabled={disabled || busy} /></label>
      </div>
      <label className="fieldLabel">Consent evidence/reference (kept locally)<textarea name="note" aria-label="Consent evidence note" maxLength={1000} disabled={disabled || busy} /></label>
      <label className="consentCheck"><input type="checkbox" name="approved" required disabled={disabled || busy} />The rights holder authorized cloning and dubbed output for this project.</label>
      <label className="consentCheck"><input type="checkbox" name="clean" required disabled={disabled || busy} />I reviewed this range: one authorized speaker, no overlapping voices or music.</label>
      <label className="consentCheck"><input type="checkbox" name="upload" required disabled={disabled || busy} />I have permission to upload this reference to the selected provider when I register it.</label>
      <button className="smallButton" disabled={disabled || busy || !project.speakers.length}>Save consented reference</button>
      {dirty && <button type="button" className="smallButton" disabled={disabled || busy} onClick={() => {
        if (!window.confirm("Discard this unsaved reference and consent draft? No saved consent or provider copy will change.")) return;
        formRef.current?.reset(); markDirty(false); setError(null);
      }}>Discard reference draft</button>}
    </form>
    {dirty && <p className="lineWarning" role="status">Unsaved reference draft. Nothing has been saved or uploaded from this form. Draft values stay in this open page only; save or explicitly discard before leaving.</p>}
    {provider === "sarvam" && <label className="fieldLabel">Registration allowance (INR, not a verified tariff)<input aria-label="Registration allowance INR" type="number" min="0.01" max="1000" step="0.01" value={allowance} onChange={(event) => setAllowance(event.target.value)} />
      <small>Exact enrollment billing and account voice limits need live verification. This amount reserves project budget, not a provider spending cap.</small></label>}
    {clones.map((profile) => {
      const speaker = project.speakers.find((item) => item.id === profile.speaker_id);
      const reference = project.artifacts.find((item) => item.id === profile.reference_artifact_id);
      const active = speaker?.voice_profile_id === profile.id;
      const revoked = profile.consent_status !== "approved";
      const profileAvailable = profile.provider === "fake" || (profile.provider === provider && available);
      const uncertain = project.jobs.some((job) => job.voice_profile_id === profile.id && ["uncertain_registration", "uncertain_submission"].includes(job.error_code ?? ""));
      return <section key={profile.id} className="cloneCard" aria-label={`Voice reference ${profile.display_name}`}>
        <h3>{profile.display_name} {active && <small>Selected voice</small>}</h3>
        <p>{profile.provider === "fake" ? "Demo only — no voice cloned" : "Consented clone · beta"} · {profile.registration_status} · Consent: {profile.consent_status}</p>
        {profile.consent_status === "recovery_hold" && <p className="lineWarning">Restored permission is historical. Verify current rights and create a fresh consented reference before use. No provider copy was deleted; explicit revocation is required before cleanup.</p>}
        {reference && !reference.access_blocked_reason && <audio controls preload="none" aria-label={`Reference audio ${profile.display_name}`} src={`${API_URL}${reference.content_url}`} />}
        {reference?.access_blocked_reason && <p className="lineWarning">{reference.access_blocked_reason}</p>}
        {(reference?.metadata_json.quality as { warnings?: string[] } | undefined)?.warnings?.map((warning) => <p className="lineWarning" key={warning}>{warning}</p>)}
        {uncertain && profile.registration_status === "prepared" && <p className="lineWarning">An upload has an unknown outcome. Inspect the provider&apos;s saved voices and usage before retrying; another upload may create a duplicate.</p>}
        {profile.registration_status === "unprepared" && !revoked && <button className="smallButton" disabled={disabled || busy}
          onClick={() => onRun({ stage: "prepare_reference", voice_profile_id: profile.id })}>Prepare reference</button>}
        {profile.registration_status === "prepared" && !revoked && <>
          <label className="consentCheck"><input type="checkbox" aria-label={`Reviewed reference ${profile.display_name}`} checked={!!reviewed[profile.id]} onChange={(event) => setReviewed({ ...reviewed, [profile.id]: event.target.checked })} />I listened to the prepared clip and confirm it is suitable for this speaker.</label>
          <button className="smallButton" disabled={disabled || busy || !reviewed[profile.id] || !profileAvailable || (profile.provider === "sarvam" && !(Number(allowance) > 0))}
            onClick={() => { if (uncertain && !window.confirm("Have you inspected the provider's saved voices and usage? Retrying may create or charge another voice. Continue explicitly?")) return;
              void onRun({ stage: "register_voice", provider: profile.provider as "fake" | "sarvam", voice_profile_id: profile.id, reference_reviewed: true, force_new: uncertain,
                registration_allowance_inr: profile.provider === "sarvam" ? Number(allowance) : undefined }); }}>{uncertain ? "Retry registration after provider check" : profile.provider === "fake" ? "Register demo reference" : "Upload and register with Sarvam"}</button>
        </>}
        {profile.registration_status === "ready" && !revoked && speaker && <button className="smallButton" disabled={disabled || busy || active}
          onClick={() => action(() => api.selectVoiceProfile(speaker, profile.id))}>{active ? "Selected voice" : profile.provider === "fake" ? "Use demo profile" : "Use this clone"}</button>}
        {profile.consent_status !== "revoked" && <button className="smallButton" disabled={busy} onClick={() => revoke(profile)}>Revoke consent</button>}
        {profile.consent_status === "revoked" && profile.provider_voice_id && profile.registration_status !== "deleted" && <button className="smallButton" disabled={disabled || busy || !profileAvailable}
          onClick={() => { if (window.confirm("Delete this saved voice and its reference assets from the provider? Other applications using this voice will lose access. Local audit history is retained."))
            void onRun({ stage: "delete_voice", provider: profile.provider as "fake" | "sarvam", voice_profile_id: profile.id }); }}>Delete provider copy</button>}
        <button className="smallButton" onClick={() => action(async () => { const records = await api.voiceConsentHistory(profile.id); setHistory({ ...history, [profile.id]: records }); })}>Show consent history</button>
        {history[profile.id] && <ul>{history[profile.id].map((record) => <li key={record.id}>{record.status} · {record.attested_by} · {new Date(record.attested_at).toLocaleString()} {record.note && `— ${record.note}`}</li>)}</ul>}
      </section>;
    })}
    {error && <p className="inlineError" role="alert">{error}</p>}
  </details>;
}

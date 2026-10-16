# ADR 0004: Scoped voice consent and explicit saved-voice enrollment

Status: implemented, 2026-10-14. Live Sarvam enrollment/synthesis/deletion and listening acceptance remain pending credentials and authorized recordings.

## Decision

Keep stock voices and clones as different profile kinds. A speaker selects one explicit profile. Creating a clone or rerunning a job never silently replaces that choice. A stock voice is the deliberate fallback if a clone fails or its consent is revoked.

Record project, provider, rights holder, attester, reference asset/range, upload permission, single-speaker attestation, note, timestamp and consent-terms version. This is an auditable user attestation, not independent proof of identity, legal rights or a clean single-speaker recording. Legacy generic approvals do not satisfy the new scoped check.

Use separately retryable jobs:

1. Prepare a user-selected 10–15 second reference locally as 24 kHz mono PCM16. Preserve source/range, checksum and measured level/clipping warnings. Reject silent/too-quiet clips and ranges known to contain another assigned speaker. Do not label level measurement as speaker recognition or speech-emotion inference.
2. After the editor listens and confirms, upload once using the voice-cloner adapter. Sarvam saves the voice remotely; persist its returned identity and reference text. Enrollment is an explicit external action, not a side effect of saving consent. Require a user-entered INR allowance because enrollment billing and account-specific limits are not verified; this is a budget estimate, not a provider charge cap.
3. Select the ready voice explicitly. Generate candidates only from approved translated dialogue, recording profile version and consent record. Clone inputs use the documented 1000-character limit, not the stock model's larger limit. Request provider QC but require listening review; QC is not a guarantee of transcript accuracy, acting or identity fidelity.
4. Revocation immediately blocks new operations, cancels dependent queued/running work where possible, clears affected selected takes and quarantines reference/candidate/mix access. Unrelated stock takes remain intact. In-flight HTTP calls and previously downloaded copies cannot be recalled.
5. Offer a separate, explicitly confirmed provider-deletion job for a known saved voice. Keep local audit history and the tombstoned remote identifier. Do not claim local originals or downloaded exports were erased.

## Crash and concurrency behavior

The consent-reference form tracks unsaved changes separately from revision-scoped dialogue. Its values survive project refresh and switching timelines within the same mounted project. The Projects link asks before leaving; browser reload/close uses the browser's unsaved-work warning when supported. A failed save preserves the form, while a successful save resets it and clears the warning. **Discard reference draft** requires confirmation and changes only the unsaved form, never saved consent or remote data. Registration remains a separate action.

Do not persist unsaved rights-holder or evidence values in localStorage/sessionStorage. This guard is not crash recovery, a saved consent record or a guarantee for browser history navigation and every browser/device. Save the reference to make it durable. Other review/mix forms and broader navigation safeguards remain separate editor work.

Never automatically retry remote enrollment: an unsuccessful response may still have created a voice. Retain allowance consumption for uncertain outcomes and require provider inspection plus an explicit retry. Checkpoint returned remote IDs before cancellation checks so cleanup remains possible even when consent is revoked during upload. Recover known responses without submitting another creation call. Deletion is idempotent; an already-absent remote voice is success.

Check current consent before paid synthesis attempts and artifact delivery. Consent-dependent rendered outputs retain candidate/profile lineage; direct downloads and byte-range/HEAD requests use the same access gate. Switching a profile invalidates candidate selection without altering approved text. Earlier consented artifacts remain history until revocation, not automatically accepted takes.

## Evidence and limitations

Integration tests cover local reference audio, forbidden scopes/ranges, explicit selection, revocation/quarantine, stock fallback, budget allowances, uncertain and cancelled enrollment, recovery, and provider deletion. Recorded HTTP contracts cover Sarvam create/clone/delete, multipart fields and `audio_b64`; they are not live provider execution. Browser tests use synthetic tones and clearly labeled demo enrollment—no real voice was cloned.

Authoritative provider references checked on 2026-10-14: [create voice](https://docs.sarvam.ai/api-reference/voice-cloning/create-voice), [generate cloned speech](https://docs.sarvam.ai/api-reference/voice-cloning/clone), [reference preparation](https://docs.sarvam.ai/api/api-guides-tutorials/voice-cloning/how-to/prepare-reference-audio), [QC limitations](https://docs.sarvam.ai/api/api-guides-tutorials/voice-cloning/how-to/use-quality-control). Beta docs disagree on plan voice counts, so no account entitlement is assumed. Actual access, retention, billing and Malayalam quality must be verified before release.

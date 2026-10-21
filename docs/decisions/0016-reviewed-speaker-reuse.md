# Reviewed character reuse across revisions

Status: implemented for the local workspace. This is a human identity decision, not cross-run biometric speaker recognition.

## Decision

Keep transcription-created speakers scoped to their revision. Do not assume that provider speaker numbers, names or ordering identify the same actor on another run. An editor may explicitly reuse an earlier same-project speaker's display name and optionally its selected stock voice/pace after auditioning both performances.

The collapsed **Reuse earlier character** panel loads earlier speakers only when opened/refreshed, up to 500 records. Choose a current speaker, an earlier character and the optional stock-voice copy, then preview. Application requires a separate acknowledgement and no unsaved editor drafts. History loads on demand and shows the latest 20 operations for the selected target speaker.

## Frozen preview and application

The preview hash covers the active revision, source and target speaker state/timestamps, selected profile identity/version/settings/consent status, copy choice and all current non-retired target lines. Foreign-project, same/later revision and inactive-target mappings are refused. Copying validates the supported stock catalog and pace constraints. The API checks these boundaries independently of the UI.

Application takes the SQLite write reservation, refuses active jobs and compares the frozen hash before making changes. A changed name, selected voice, voice parameters, dialogue/version or active revision requires a new preview. Update the target name and, when explicitly requested, create a separate preset profile owned by the current speaker with the chosen stock ID/pace. Never move or mutate the earlier profile.

Affected current lines retain their text, speaker ID and timing, but are marked as manually edited and require approval again: clear selected audio, increment versions and append line-edit evidence. Earlier revisions, inactive lines, original takes and profiles remain historical. Briefs and their character directions are not copied; inspect the current revision's context separately. Unrelated speakers and lines are untouched.

Append an operation containing source/target IDs, fingerprint, before snapshot and resulting target/profile/line versions. A repeated request with a recorded fingerprint returns that historical operation without reapplying it, even if the target was edited later. Replay never overwrites a later correction. This is not an undo endpoint; correct the current name/voice explicitly and retain the audit trail.

## Consent boundary

Never copy a cloned profile or infer new permission from an old label. Name-only reuse keeps the target's current voice selection and does not grant, renew or revoke consent. If a clone is needed for the new speaker record, use a fresh scoped consent-reference workflow. Mapping itself makes no provider request, uploads no reference and consumes no AI budget.

## Migration and acceptance

Migration `0010_speaker_reuse` adds an append-only application audit table without rewriting existing speakers, approvals, selected takes, profiles or consent. Startup from schema 0009 first creates a consistent sibling `v02-structure` database-only backup. Use the full [workspace recovery procedure](../recovery.md) for database plus media recovery; schema verification requires a matching checkout. Destructive downgrade is unsupported.

Backend checks cover separate profile ownership, unchanged text/timing, approval/take invalidation, replay without reapplication, stale source/target/voice/line inputs, missing confirmation, active jobs, wrong revisions, foreign projects, invalid stock settings and clone refusal. Upgrade checks compare unchanged existing rows and the schema-0009 backup. Browser evidence covers manual name/pace preparation, a new transcription revision, stale-preview refusal, explicit application, unchanged Malayalam text, separate stock profiles, saved history after reload and mobile layout.

Natural-scene identity review, live Sarvam verification, broader long-session performance and automatic identity suggestions remain open. No embeddings or model confidence score are fabricated. A manually reused name is not proof of actor identity, natural vocal similarity or permission.

Final milestone verification: 188 backend tests, six browser workflows (reuse plus core media/editor/voice/consent/history), contracts, strict types, lint/format and production build passed. The mobile panel screenshot was inspected. The full suite ran sequentially after an initial shared Next.js server conflict; the interrupted attempt is not passing evidence. No paid request, model download or normal-workspace migration was performed.

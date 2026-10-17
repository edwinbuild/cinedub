# ADR 0002: Revisions, explicit media inputs and resumable jobs

Accepted for v0.2.

Every transcription creates a new timeline revision, with speakers and lines scoped to it. Projects select one active revision. First imports activate automatically; reruns never activate over existing reviewed work. Switching revisions requires an optimistic active-revision check and retains history.

Jobs snapshot source assets, revision IDs, text versions, provider/model/style, and estimated INR rates. A job never resolves “latest upload” while running. Subtitle exports use the scheduled line versions so subsequent edits cannot silently change their provenance. Human saves and translation application use atomic version predicates. Newer human edits win; unused model candidates stay in job artifacts.

Only one local worker per SQLite database is supported; an OS advisory lock enforces this even when processes use different storage roots. Other databases use a storage-root lock until a dedicated multi-worker queue is implemented. Queue claims also use a conditional update. Restart recovery requeues safe local work and resumes known remote batch jobs. Creation/translation outcomes interrupted at an uncertain request boundary require explicit investigation/retry. This deliberately does not claim exactly-once execution against an external API without an idempotency contract.

Estimated budgets are reserved transactionally under SQLite's write lock before jobs are queued. Each dispatched paid attempt consumes its estimated charge; unknown outcomes remain counted. Budgets are advisory monetary controls, not reconciliation against provider billing. Rates are snapshotted, configurable and visible. Safe transient retries are bounded and cancellation-aware; ambiguous paid transport errors are not automatically repeated.

Recognized storage-capacity failures are fail-stop boundaries. API requests receive a generic HTTP 507 without copying SQL/parameters into the response. The worker rolls back and exits nonzero rather than reporting false completion or repeatedly attempting to persist errors to full storage. Its last durable running/checkpoint state remains available for normal restart recovery after capacity is restored. Ambiguous paid boundaries remain held, while committed local artifacts can be reused idempotently. Classification uses SQLite/OS error codes, not untrusted exception text; unrelated failures retain their existing behavior. See [operational steps and bounded fault-injection evidence](../recovery.md#when-storage-capacity-is-exhausted). This does not claim physical disk-full or power-loss durability.

Migrations freeze historical schema definitions instead of importing current ORM models. Application startup backs up v0.1 SQLite databases before applying the revision migration. Restore that backup to roll back; there is no destructive revision downgrade.

## Manual stock generation variation

The application-owned `variation` setting maps to Bulbul v3 `temperature` only in the Sarvam adapter. The [official REST reference](https://docs.sarvam.ai/api-reference/text-to-speech/convert), checked 2026-10-17, documents a 0.01–1 range and 0.6 default. It is randomness/expressiveness control, not an emotion label, calibrated score or acting guarantee. No classifier result changes it automatically; unsupported pitch/loudness/SSML controls are not invented.

Only Sarvam stock profiles support it. The API rejects unsupported/demo settings and nonfinite/out-of-range values. New jobs freeze the resolved value into voice snapshots, cache signatures, provider-run evidence and candidates before any estimated charge. Stock reuse preserves explicit variation. Old profiles/results are not rewritten; absent historical settings resolve to the explicitly chosen 0.6 for new jobs only. Unfinished legacy Sarvam stock work without a frozen value fails before another call: inspect usage/checkpoints before submitting new work. Already-published historical artifacts remain unchanged.

The editor uses explicit Save/Discard and selected-profile/version predicates. Same-profile refresh and failed saves retain the variation draft; a newer profile version blocks it until discarded/copied. A change clears selected takes, not text approvals, and saving settings never synthesizes speech. Legacy callers may omit the new optional concurrency fields; the current editor sends them. Drafts are page memory, not crash recovery or universal navigation protection; changing the selected voice or leaving the editor can remove them. Live listening, pronunciation, timing and natural performance acceptance remain required. Sampling is not exact deterministic replay.

References: [Batch transcription](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/batch-api), [translation models](https://docs.sarvam.ai/api-reference/text/translate-text).

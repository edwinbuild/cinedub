# ADR 0002: Revisions, explicit media inputs and resumable jobs

Accepted for v0.2.

Every transcription creates a new timeline revision, with speakers and lines scoped to it. Projects select one active revision. First imports activate automatically; reruns never activate over existing reviewed work. Switching revisions requires an optimistic active-revision check and retains history.

Jobs snapshot source assets, revision IDs, text versions, provider/model/style, and estimated INR rates. A job never resolves “latest upload” while running. Subtitle exports use the scheduled line versions so subsequent edits cannot silently change their provenance. Human saves and translation application use atomic version predicates. Newer human edits win; unused model candidates stay in job artifacts.

Only one local worker per SQLite database is supported; an OS advisory lock enforces this even when processes use different storage roots. Other databases use a storage-root lock until a dedicated multi-worker queue is implemented. Queue claims also use a conditional update. Restart recovery requeues safe local work and resumes known remote batch jobs. Creation/translation outcomes interrupted at an uncertain request boundary require explicit investigation/retry. This deliberately does not claim exactly-once execution against an external API without an idempotency contract.

Estimated budgets are reserved transactionally under SQLite's write lock before jobs are queued. Each dispatched paid attempt consumes its estimated charge; unknown outcomes remain counted. Budgets are advisory monetary controls, not reconciliation against provider billing. Rates are snapshotted, configurable and visible. Safe transient retries are bounded and cancellation-aware; ambiguous paid transport errors are not automatically repeated.

Migrations freeze historical schema definitions instead of importing current ORM models. Application startup backs up v0.1 SQLite databases before applying the revision migration. Restore that backup to roll back; there is no destructive revision downgrade.

References: [Batch transcription](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/batch-api), [translation models](https://docs.sarvam.ai/api-reference/text/translate-text).

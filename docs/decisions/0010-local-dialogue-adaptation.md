# ADR 0010 Bounded local dialogue adaptation

Status: experimental English to Malayalam draft generation, 2026-10-15. Human language, meaning and performance acceptance remain open.

## Separate stage and interchangeable adapter

`adapt_dialogue` is an optional stage behind the provider-neutral `DialogueAdapter` contract. Plain Sarvam translation remains unchanged. The stage freezes the saved scene brief, character direction, preferred terms, source/draft text, neighboring lines and exact time windows. It returns faithful and concise alternatives without changing the timeline. Model notes are unverified generated text, not speech-emotion analysis.

Logical request fingerprints are independent of vendor chat serialization. The local adapter separately fingerprints its actual serialized prompt. Each result records model revision, prompt version, parameters, engine identity, latency, token count and local resource measurements. Future adapters can consume the same context and result contracts; routing still needs an implemented, configured and evaluated adapter rather than silently accepting another model file.

## Pinned CPU profile

The optional model is [Unsloth's Q4_K_M conversion](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF) of [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507). Both cards declare Apache-2.0. This is a text model, not a speech or voice-cloning model.

| Component | Pinned identity |
| --- | --- |
| GGUF repository revision | `a06e946bb6b655725eafa393f4a9745d460374c9` |
| File | `Qwen3-4B-Instruct-2507-Q4_K_M.gguf`, 2,497,281,120 bytes |
| Model SHA256 | `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` |
| Official CPU runtime | [llama.cpp b11642](https://github.com/ggml-org/llama.cpp/releases/tag/b11642), commit `2639a3b4e029d1be80ca4a472d62dfea23609075` |
| Runtime archive SHA256 | `374efdb7638a3b3c06eda2a384485015ecf751f172364a4309be88e7bdaa1aa7` |

Setup explicitly downloads into ignored `models/qwen3-dialogue/`. It verifies the model/archive and compares installed executables, libraries and symlinks with the pinned archive before execution. No installer shell, global package, service, GPU or PyTorch is required. This packaged profile currently supports Linux x86_64 only; other platforms need their own verified runtime adapter.

Each native process uses four CPU threads by default, a 4096-token context, a 768-token generation limit and a 10 GiB address-space cap. The parent enforces the configured job deadline, defaults to 1800 seconds, strips credentials from the environment and stops the whole process group on cancellation. Tokenization and generation are sequential; the native model exits after each line. The profile targets a 24 GB laptop, but the process cap and a short benchmark are not a whole-application or every-scene memory guarantee.

## Output and recovery boundaries

The tokenizer checks the actual prompt-token count before generation. Over-budget context fails with an instruction to shorten it; context is never silently dropped. Output uses a JSON grammar and shared validation. Only the pinned CLI's exact end-of-generation transport suffix is removed; malformed, truncated or mismatched output is not repaired into a passing result. Prompt data escapes chat delimiters, and generated text remains untrusted.

Completed lines are validated and committed to job checkpoints. Restart or an explicit safe retry reuses only those database-committed lines, never an arbitrary leftover file. A persisted report and its run records are reused without duplication. Late context changes stop publication. Historical reads verify bytes, frozen inputs and committed model output without depending on the current prompt implementation.

## Explicit editor application

Applying an alternative requires the current line version, an active matching revision, no active project job and a language-review confirmation. Replacing edited/approved text and proceeding despite terminology/number warnings need separate confirmations. Wrong-script or model-control-marker output cannot be applied through this route. The editor may correct it manually.

Changing text records edit history, clears selected voice audio and sets `needs_review`; timing is preserved. Applying identical text is a no-op. Known applications from the same report remain auditable and allow other lines in that report to be reviewed. Unrelated source, timing, speaker, translation or brief changes mark the report stale. Old drafts and exports remain historical evidence rather than being overwritten.

## Quality acceptance

The original two-prompt context smoke check and real-model browser workflow establish execution, basic context sensitivity and safeguards. They do not establish fluent cinema Malayalam, exact intent, natural speaking duration or preserved performance. [Measured examples and remaining evaluation](../evaluations/local-dialogue-adaptation.md) define the next gate. Do not replace the plain translation default or automate approvals based on these fixtures.

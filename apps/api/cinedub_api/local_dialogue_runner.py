"""Disposable CPU inference: constrained JSON, explicit token budget and reusable line results."""

import argparse
import hashlib
import json
import resource
import subprocess
import time
from pathlib import Path

from .dialogue_prompt import GENERATION, PROMPT_VERSION, request_digest
from .providers.local_dialogue import (
    EXECUTABLE,
    MODEL_FILE,
    MODEL_NAME,
    qwen_prompt,
    read_manifest,
    serialized_prompt_digest,
)
from .schemas import DialogueModelOutput


def atomic_json(path, value):
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    pending.replace(path)


def native_call(command, directory, label):
    # The parent owns the process group/deadline. This child and every native process
    # share that group so cancellation stops tokenization and generation together.
    with (directory / f"{label}.stderr.log").open("w") as log:
        output_path = directory / f"{label}.stdout.txt"
        with output_path.open("wb") as output:
            subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output, stderr=log, check=True)
    if output_path.stat().st_size > 100_000:
        raise ValueError("Native dialogue output exceeds the supported bound")
    return output_path.read_text(encoding="utf-8").strip()


def decode_generation(response):
    # The pinned CLI appends this transport marker after an end-of-generation token.
    # Strip only that exact suffix, never extract/repair arbitrary malformed JSON.
    if not response.endswith("[end of text]"):
        raise ValueError("Dialogue generation did not reach its end token; output may be truncated")
    return DialogueModelOutput.model_validate_json(response.removesuffix("[end of text]").rstrip())


def generate(directory, output_dir, request, index, threads):
    runtime = directory / "runtime" / Path(EXECUTABLE).parent
    model = directory / MODEL_FILE
    prompt = output_dir / f"prompt-{index}.txt"
    prompt.write_text(qwen_prompt(request), encoding="utf-8")
    tokenizer = native_call(
        [
            str(runtime / "llama-tokenize"),
            "--model",
            str(model),
            "--file",
            str(prompt),
            "--ids",
            "--no-bos",
            "--no-escape",
            "--offline",
            "--log-disable",
        ],
        output_dir,
        f"tokenize-{index}",
    )
    tokens = json.loads(tokenizer)
    if (
        not isinstance(tokens, list)
        or not tokens
        or not all(type(token) is int for token in tokens)
    ):
        raise ValueError("Native tokenizer did not return token IDs")
    if len(tokens) + GENERATION["max_output_tokens"] + 16 > GENERATION["context_tokens"]:
        raise ValueError(
            "Dialogue context exceeds 4096 tokens; shorten the brief or neighboring dialogue"
        )
    schema_path = output_dir / "output-schema.json"
    schema_path.write_text(json.dumps(DialogueModelOutput.model_json_schema()), encoding="utf-8")
    started = time.monotonic()
    response = native_call(
        [
            str(runtime / "llama-completion"),
            "--model",
            str(model),
            "--file",
            str(prompt),
            "--json-schema-file",
            str(schema_path),
            "--ctx-size",
            str(GENERATION["context_tokens"]),
            "--n-predict",
            str(GENERATION["max_output_tokens"]),
            "--temp",
            "0",
            "--seed",
            "42",
            "--threads",
            str(threads),
            "--threads-batch",
            str(threads),
            "--batch-size",
            "256",
            "--ubatch-size",
            "128",
            "--gpu-layers",
            "0",
            "--device",
            "none",
            "--fit",
            "off",
            "--no-context-shift",
            "--no-conversation",
            "--no-display-prompt",
            "--simple-io",
            "--no-escape",
            "--no-warmup",
            "--offline",
            "--color",
            "off",
        ],
        output_dir,
        f"generate-{index}",
    )
    parsed = decode_generation(response)
    return {
        "segment_id": request["segment_id"],
        "output": parsed.model_dump(),
        "prompt_sha256": serialized_prompt_digest(request),
        "request_sha256": request_digest(request),
        "prompt_tokens": len(tokens),
        "latency_ms": round((time.monotonic() - started) * 1000),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--threads", type=int, required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (10 * 1024**3, 10 * 1024**3))
    read_manifest(args.model_dir)
    payload = json.loads(args.request.read_text(encoding="utf-8"))
    if payload.get("prompt_version") != PROMPT_VERSION or payload.get("parameters") != GENERATION:
        raise ValueError("Unsupported dialogue prompt/generation version")
    identity = hashlib.sha256(args.request.read_bytes()).hexdigest()
    partial = args.output_dir / "adaptation-partial.json"
    # Only database-committed results supplied by the parent are reusable. An
    # interrupted process's uncommitted file is never treated as model evidence.
    state = {"input_sha256": identity, "lines": payload.get("completed_lines", [])}
    if len(state["lines"]) > len(payload["lines"]):
        raise ValueError("Partial dialogue results exceed requested lines")
    for index, result in enumerate(state["lines"]):
        request = payload["lines"][index]
        if (
            result["segment_id"] != request["segment_id"]
            or result["prompt_sha256"] != serialized_prompt_digest(request)
            or result["request_sha256"] != request_digest(request)
        ):
            raise ValueError("Partial dialogue provenance changed")
        DialogueModelOutput.model_validate(result["output"])
    started = time.monotonic()
    atomic_json(partial, state)
    atomic_json(
        args.output_dir / "progress.json",
        {"completed": len(state["lines"]), "total": len(payload["lines"])},
    )
    for index in range(len(state["lines"]), len(payload["lines"])):
        request = payload["lines"][index]
        state["lines"].append(
            generate(args.model_dir, args.output_dir, request, index, args.threads)
        )
        atomic_json(partial, state)
        atomic_json(
            args.output_dir / "progress.json",
            {"completed": index + 1, "total": len(payload["lines"])},
        )
    atomic_json(
        args.output_dir / "adaptation-result.json",
        {
            "provider": "local",
            "model": MODEL_NAME,
            "prompt_version": PROMPT_VERSION,
            "parameters": GENERATION,
            "lines": state["lines"],
            "runtime": {
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "peak_rss_mib": round(
                    resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1
                ),
                "threads": args.threads,
            },
        },
    )


if __name__ == "__main__":
    main()

"""Disposable, optional local source/take measurements and Malayalam CTC suggestions."""

import importlib.util
import json

from ..local_process import run_inference


def availability():
    return importlib.util.find_spec("numpy") is not None


class LocalTakeAnalyzer:
    name = "local"

    def __init__(self, threads=4, timeout_seconds=900):
        self.threads, self.timeout_seconds = threads, timeout_seconds

    def compare(self, request, output_dir, *, cancel, progress):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "take-analysis-input.json"
        path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        run_inference(
            "cinedub_api.local_take_analysis_runner",
            [
                "--request",
                str(path.resolve()),
                "--output-dir",
                str(output_dir.resolve()),
                "--threads",
                str(self.threads),
            ],
            output_dir,
            threads=self.threads,
            timeout_seconds=self.timeout_seconds,
            cancel=cancel,
            progress=progress,
        )
        return json.loads((output_dir / "take-analysis-result.json").read_text())

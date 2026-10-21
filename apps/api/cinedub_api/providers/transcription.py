"""Official SDK hidden behind a resumable application interface."""

import json
from pathlib import Path

import httpx
from sarvamai import SarvamAI
from sarvamai.environment import SarvamAIEnvironment


class SarvamTranscriber:
    name = "sarvam"

    def __init__(self, api_key: str, base_url: str):
        if not api_key:
            raise ValueError("SARVAM_API_KEY is not configured")
        base = base_url.rstrip("/")
        self.client = SarvamAI(
            api_subscription_key=api_key,
            timeout=45,
            environment=SarvamAIEnvironment(
                base=base, creative=f"{base}/dubbing", production=base.replace("https://", "wss://")
            ),
        )

    def create(self, model: str, language: str, num_speakers: int | None) -> str:
        return self.client.speech_to_text_job.create_job(
            model=model,
            mode="transcribe",
            language_code=language,
            with_diarization=True,
            with_timestamps=True,
            num_speakers=num_speakers,
            request_options={"max_retries": 0},
        ).job_id

    def upload(self, job_id: str, audio_path: Path) -> None:
        links = self.client.speech_to_text_job.get_upload_links(
            job_id=job_id, files=[audio_path.name], request_options={"max_retries": 0}
        )
        url = links.upload_urls[audio_path.name].file_url
        with audio_path.open("rb") as audio:
            response = httpx.put(
                url,
                content=audio,
                headers={"x-ms-blob-type": "BlockBlob", "Content-Type": "audio/wav"},
                timeout=60,
            )
        response.raise_for_status()

    def start(self, job_id: str) -> None:
        self.client.speech_to_text_job.start(job_id=job_id, request_options={"max_retries": 0})

    def status(self, job_id: str) -> str:
        result = self.client.speech_to_text_job.get_status(
            job_id, request_options={"max_retries": 0}
        )
        if result.job_state == "Completed" and result.failed_files_count:
            raise ValueError("Sarvam could not transcribe this file; inspect the source audio")
        return result.job_state

    def result(self, job_id: str, output_dir: Path) -> dict:
        status = self.client.speech_to_text_job.get_status(
            job_id, request_options={"max_retries": 0}
        )
        files = [
            output.file_name
            for detail in status.job_details or []
            if detail.state == "Success"
            for output in detail.outputs or []
        ]
        if len(files) != 1:
            raise ValueError("Expected exactly one transcript output")
        links = self.client.speech_to_text_job.get_download_links(
            job_id=job_id, files=files, request_options={"max_retries": 0}
        )
        response = httpx.get(links.download_urls[files[0]].file_url, timeout=45)
        response.raise_for_status()
        payload = response.json()
        output_dir.mkdir(parents=True, exist_ok=True)
        # Provider filenames never become local paths.
        (output_dir / "provider-result.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return payload

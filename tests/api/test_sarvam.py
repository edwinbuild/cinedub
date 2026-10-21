import json
from types import SimpleNamespace

import httpx
import pytest
from cinedub_api.providers.retry import retry_safe
from cinedub_api.providers.sarvam import SarvamProvider
from cinedub_api.providers.transcription import SarvamTranscriber
from sarvamai import SarvamAI


def test_official_sdk_batch_request_contract(monkeypatch, tmp_path):
    requests = []
    job_info = {
        "job_id": "recorded",
        "storage_container_type": "Azure",
        "job_parameters": {},
        "job_state": "Completed",
        "created_at": "2026-10-14",
        "updated_at": "2026-10-14",
        "failed_files_count": 0,
        "job_details": [
            {
                "state": "Success",
                "inputs": [{"file_name": "recognition.wav", "file_id": "in"}],
                "outputs": [{"file_name": "0.json", "file_id": "out"}],
            }
        ],
    }

    def handle(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("upload-files"):
            return httpx.Response(
                200,
                json={
                    **job_info,
                    "upload_urls": {
                        "recognition.wav": {"file_url": "https://storage.invalid/upload"}
                    },
                },
            )
        if path.endswith("download-files"):
            assert json.loads(request.content)["files"] == ["0.json"]
            return httpx.Response(
                200,
                json={
                    **job_info,
                    "download_urls": {"0.json": {"file_url": "https://storage.invalid/result"}},
                },
            )
        return httpx.Response(200, json=job_info)

    provider = SarvamTranscriber("test-only", "https://api.invalid")
    provider.client = SarvamAI(
        api_subscription_key="test-only",
        httpx_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    assert provider.create("saaras:v4", "en-IN", 2) == "recorded"
    body = json.loads(requests[0].content)
    assert body["job_parameters"]["model"] == "saaras:v4"
    assert body["job_parameters"]["mode"] == "transcribe"
    assert body["job_parameters"]["with_diarization"] is True
    assert body["job_parameters"]["with_timestamps"] is True
    audio = tmp_path / "recognition.wav"
    audio.write_bytes(b"RIFF-fixture")

    def put(url, *, content, headers, timeout):
        assert content.read() == b"RIFF-fixture" and headers["Content-Type"] == "audio/wav"
        return httpx.Response(201, request=httpx.Request("PUT", url))

    monkeypatch.setattr(httpx, "put", put)
    provider.upload("recorded", audio)
    provider.start("recorded")
    assert provider.status("recorded") == "Completed"
    payload = {"transcript": "Recorded transcript", "diarized_transcript": {"entries": []}}
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **_: httpx.Response(200, json=payload, request=httpx.Request("GET", url)),
    )
    assert provider.result("recorded", tmp_path / "results") == payload
    assert (tmp_path / "results" / "provider-result.json").is_file()


def test_translation_payload_model_and_style(monkeypatch):
    payloads = []

    def post(url, *, headers, json, timeout):
        payloads.append(json)
        return httpx.Response(
            200,
            json={"translated_text": "മലയാളം", "request_id": "recorded"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", post)
    provider = SarvamProvider("test-only", "https://api.invalid")
    result = provider.translate("Hello", "en-IN", "ml-IN")
    assert result.text == "മലയാളം" and result.request_id == "recorded"
    assert payloads[-1]["model"] == "mayura:v1"
    assert payloads[-1]["mode"] == "modern-colloquial"
    provider.model = "sarvam-translate:v1"
    provider.translate("Hello", "en-IN", "ml-IN")
    assert payloads[-1]["mode"] == "formal"


def test_retry_is_bounded_and_cancellable(monkeypatch):
    import cinedub_api.providers.retry as module

    # Advance a fake clock instead of waiting during a unit test.
    clock = SimpleNamespace(value=0)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock.value)
    monkeypatch.setattr(
        module.time, "sleep", lambda value: setattr(clock, "value", clock.value + value)
    )
    calls = []

    def operation():
        calls.append(1)
        request = httpx.Request("POST", "https://api.invalid")
        response = httpx.Response(429, headers={"Retry-After": "2"}, request=request)
        raise httpx.HTTPStatusError("rate limit", request=request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        retry_safe(operation, lambda: None)
    assert len(calls) == 3 and clock.value >= 4
    calls.clear()
    with pytest.raises(InterruptedError):
        retry_safe(operation, lambda: (_ for _ in ()).throw(InterruptedError()))
    assert not calls


def test_ambiguous_billed_connection_is_not_retried():
    calls = []

    def operation():
        calls.append(1)
        raise httpx.ReadTimeout("Unknown server outcome")

    with pytest.raises(httpx.ReadTimeout):
        retry_safe(operation, lambda: None, lambda: None)
    assert len(calls) == 1

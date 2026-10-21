from pathlib import Path

from cinedub_api.providers.fake import FakeProvider


def test_fake_provider_is_deterministic(tmp_path: Path):
    provider = FakeProvider()
    first = provider.translate("Welcome to CineDub.", "en-IN", "ml-IN")
    second = provider.translate("Welcome to CineDub.", "en-IN", "ml-IN")
    assert first == second
    assert first.text == "സിനിഡബിലേക്ക് സ്വാഗതം."

    output = tmp_path / "candidate.wav"
    result = provider.synthesize("സിനിഡബ്", "ml-IN", output, voice_id="speaker-a")
    assert result.audio_path == output
    assert output.read_bytes().startswith(b"RIFF")

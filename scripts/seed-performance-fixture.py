"""Seed original eSpeak speech ONLY into an explicitly supplied isolated E2E database.

This is test infrastructure, not an application route or a production voice adapter.
It cannot target the user's workspace database, enroll a voice or make a paid call.
"""

import argparse
import os
import subprocess
from pathlib import Path
from uuid import UUID

ENGLISH = "Hello world. This is a simple test."
MALAYALAM = "നമസ്കാരം. ഇത് ഒരു ചെറിയ പരീക്ഷണം ആണ്."


def seed(state_root, project_id):
    if (
        state_root.is_symlink()
        or state_root.resolve().parent != Path("/tmp")
        or not state_root.name.startswith("cinedub-e2e-")
        or not state_root.is_dir()
        or not (state_root / "cinedub.db").is_file()
        or (state_root / "cinedub.db").is_symlink()
        or (state_root / "storage").resolve().parent != state_root.resolve()
    ):
        raise ValueError("Only an existing isolated /tmp/cinedub-e2e-* test database is allowed")
    UUID(project_id)
    os.environ["CINEDUB_DATABASE_URL"] = f"sqlite:///{state_root.resolve() / 'cinedub.db'}"
    os.environ["CINEDUB_STORAGE_ROOT"] = str(state_root.resolve() / "storage")
    os.environ["CINEDUB_ENV"] = "e2e"
    from cinedub_api.audio import fit_dialogue
    from cinedub_api.database import SessionLocal
    from cinedub_api.media import file_digest, run_ffmpeg
    from cinedub_api.models import Artifact, Job, Project, Segment, Speaker, VoiceProfile
    from cinedub_api.voices import candidate_signature
    from sqlalchemy import select

    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if not project or project.name != "Performance evaluation fixture":
            raise ValueError("Expected a freshly created performance evaluation test project")
        if session.scalar(
            select(Job.id).where(
                Job.project_id == project_id, Job.status.in_(("running", "queued"))
            )
        ):
            raise ValueError("Wait for test processing before seeding speech")
        line = session.scalar(
            select(Segment)
            .where(
                Segment.project_id == project_id, Segment.revision_id == project.active_revision_id
            )
            .order_by(Segment.index)
        )
        if not line or not line.speaker_id:
            raise ValueError("Prepare a test transcript with a speaker first")
        directory = state_root / "storage" / project_id / "original-synthetic-fixture"
        directory.mkdir(parents=True, exist_ok=True)
        raw, delayed, fitted = (
            directory / "malayalam.wav",
            directory / "delayed.wav",
            directory / "take.wav",
        )
        subprocess.run(
            ["espeak-ng", "-v", "ml", "-s", "135", "-w", str(raw), MALAYALAM],
            check=True,
            capture_output=True,
            timeout=30,
        )
        run_ffmpeg(["-i", str(raw), "-af", "adelay=500:all=1", str(delayed)])
        fit = fit_dialogue(delayed, fitted, line.end_ms - line.start_ms, 1.15)
        if fit["fit_status"] != "ready":
            raise ValueError("Synthetic fixture speech does not fit the prepared test line")
        profile = VoiceProfile(
            project_id=project_id,
            speaker_id=line.speaker_id,
            display_name="Synthetic test speech",
            provider="local-evaluation",
            provider_voice_id="espeak-ng-ml-fixture",
            voice_kind="preset",
            consent_status="not_required",
            registration_status="ready",
            settings_json={"pace": 1},
        )
        session.add(profile)
        session.flush()
        session.get(Speaker, line.speaker_id).voice_profile_id = profile.id
        line.source_text, line.translated_text = ENGLISH, MALAYALAM
        line.version += 1
        line.status, line.human_edited, line.selected_candidate_id = "approved", True, None
        voice = {
            "profile_id": profile.id,
            "profile_version": profile.version,
            "voice_id": profile.provider_voice_id,
            "voice_kind": "preset",
            "pace": 1,
            "provider": "local-evaluation",
            "model": "espeak-ng-ml-fixture",
        }
        material = {
            field: getattr(line, field)
            for field in ("source_text", "translated_text", "start_ms", "end_ms", "speaker_id")
        }
        candidate = Artifact(
            project_id=project_id,
            kind="dialogue_candidate",
            path=str(fitted.resolve()),
            filename="original-synthetic-malayalam-fixture.wav",
            media_type="audio/wav",
            metadata_json={
                **fit,
                "segment_id": line.id,
                "revision_id": project.active_revision_id,
                "source_version": line.version,
                "voice": voice,
                "provider": "local-evaluation",
                "model": "espeak-ng-ml-fixture",
                "signature": candidate_signature(material, voice),
                "demo": False,
                "evaluation_fixture": True,
                "sha256": file_digest(fitted),
            },
        )
        session.add(candidate)
        session.commit()
        print(candidate.id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args()
    seed(args.state_root, args.project_id)

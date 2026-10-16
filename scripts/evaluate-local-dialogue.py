"""Original context-contrast smoke check; not a Malayalam expert or cinema-quality score."""

import json
import tempfile
from pathlib import Path

from cinedub_api.dialogue_prompt import GENERATION, PROMPT_VERSION
from cinedub_api.providers.local_dialogue import LocalDialogueAdapter


def main():
    root = Path("data/evaluation")
    root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="dialogue-", dir=root)).resolve()
    lines = []
    for identifier, scene, preferred in [
        (
            "river",
            "Two friends are fishing by a river. "
            "Bank means the river shore, not a financial institution.",
            "നദിക്കര",
        ),
        (
            "finance",
            "Two colleagues are arranging a meeting at a financial bank, not by a river.",
            "ബാങ്ക്",
        ),
    ]:
        lines.append(
            {
                "segment_id": identifier,
                "data": {
                    "source_language": "en-IN",
                    "target_language": "ml-IN",
                    "scene_summary": scene,
                    "adaptation_notes": "Keep the invitation casual and concise.",
                    "character": {"intent": "Arrange a meeting", "delivery_notes": "Friendly"},
                    "speaker_name": "Ravi",
                    "source_text": "Meet me by the bank.",
                    "draft_translation": "",
                    "window_ms": 2200,
                    "previous_line": None,
                    "next_line": None,
                    "preferred_terms": [
                        {
                            "source": "bank",
                            "preferred_target": preferred,
                            "note": "Use the scene sense",
                        }
                    ],
                },
            }
        )
    result = LocalDialogueAdapter(Path("models/qwen3-dialogue")).adapt(
        {
            "prompt_version": PROMPT_VERSION,
            "parameters": GENERATION,
            "lines": lines,
            "completed_lines": [],
        },
        output,
        cancel=lambda: None,
        progress=lambda values: print(f"Completed {len(values)}/{len(lines)} lines", flush=True),
    )
    print(json.dumps({"output_directory": str(output), **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

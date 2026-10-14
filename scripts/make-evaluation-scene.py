"""Generate an original two-voice English fixture with eSpeak NG and FFmpeg.

No actor recording or downloaded film asset is needed. Output stays in ignored data/.
This fixture tests plumbing, not natural acting or cinematic model quality.
"""

import argparse
import shutil
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=Path("data/evaluation/synthetic-scene.mp4"))
args = parser.parse_args()
if not shutil.which("espeak-ng") or not shutil.which("ffmpeg"):
    parser.error("Install espeak-ng and FFmpeg to generate the synthetic scene")
args.output.parent.mkdir(parents=True, exist_ok=True)
lines = [
    ("en-us", "Welcome to our cinema workshop. Today we will review every line together."),
    (
        "en-gb+f3",
        "I agree. Please keep the meaning clear, and give us time to correct the translation.",
    ),
]
paths = []
for index, (voice, text) in enumerate(lines):
    path = args.output.parent / f"original-speaker-{index}.wav"
    subprocess.run(["espeak-ng", "-v", voice, "-s", "135", "-w", str(path), text], check=True)
    paths.append(path)
subprocess.run(
    [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(paths[0]),
        "-i",
        str(paths[1]),
        "-f",
        "lavfi",
        "-i",
        "color=c=0x101319:s=640x360:r=24",
        "-filter_complex",
        "[0:a][1:a]concat=n=2:v=0:a=1[a]",
        "-map",
        "2:v",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(args.output),
    ],
    check=True,
    timeout=60,
)
print(f"Synthetic evaluation scene: {args.output}")

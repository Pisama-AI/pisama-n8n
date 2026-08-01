#!/usr/bin/env python3
"""Verify the delivery properties of the v4 promo master."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VIDEO = ROOT / "pisama-closed-reliability-loop-v4.mp4"
CAPTIONS = ROOT / "captions.srt"


def run(*args: str) -> str:
    return subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def timestamp(value: str) -> float:
    hours, minutes, remainder = value.split(":")
    seconds, milliseconds = remainder.split(",")
    return (
        int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000
    )


def inspect_captions() -> dict[str, float | int]:
    blocks = CAPTIONS.read_text(encoding="utf-8").strip().split("\n\n")
    maximum_lines = 0
    maximum_width = 0
    maximum_cps = 0.0
    minimum_duration = float("inf")
    for block in blocks:
        lines = block.splitlines()
        match = re.fullmatch(
            r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})",
            lines[1],
        )
        assert match
        start, end = (timestamp(value) for value in match.groups())
        item_duration = end - start
        text_lines = lines[2:]
        text = " ".join(text_lines)
        maximum_lines = max(maximum_lines, len(text_lines))
        maximum_width = max(maximum_width, *(len(line) for line in text_lines))
        maximum_cps = max(maximum_cps, len(text) / item_duration)
        minimum_duration = min(minimum_duration, item_duration)
    assert maximum_lines <= 2
    assert maximum_width <= 42
    assert maximum_cps <= 20
    assert minimum_duration >= 0.9
    return {
        "entries": len(blocks),
        "max_lines": maximum_lines,
        "max_width": maximum_width,
        "max_cps": round(maximum_cps, 2),
        "min_duration": round(minimum_duration, 3),
    }


def main() -> int:
    probe = json.loads(
        run(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=index,codec_name,profile,width,height,"
            "pix_fmt,color_range,color_space,color_transfer,color_primaries,"
            "r_frame_rate,sample_rate,channels:stream_tags=language",
            "-of",
            "json",
            str(VIDEO),
        )
    )
    video, audio, captions = probe["streams"]
    media_duration = float(probe["format"]["duration"])
    size = int(probe["format"]["size"])

    assert 195 <= media_duration <= 198
    assert size < 95_000_000
    assert video["codec_name"] == "h264"
    assert video["profile"] == "High"
    assert (video["width"], video["height"]) == (1920, 1080)
    assert video["r_frame_rate"] == "30/1"
    assert video["pix_fmt"] == "yuv420p"
    assert video["color_range"] == "tv"
    assert video["color_space"] == "bt709"
    assert video["color_transfer"] == "bt709"
    assert video["color_primaries"] == "bt709"
    assert audio["codec_name"] == "aac"
    assert audio["sample_rate"] == "48000"
    assert audio["channels"] == 2
    assert captions["codec_name"] == "mov_text"
    assert captions["tags"]["language"] == "eng"

    run("ffmpeg", "-v", "error", "-i", str(VIDEO), "-f", "null", "-")
    result = {
        "captions": inspect_captions(),
        "decode": "passed",
        "duration": round(media_duration, 3),
        "size_mb": round(size / 1_000_000, 2),
        "video": "1920x1080, 30 fps, H.264 High, Rec.709",
        "audio": "AAC stereo, 48 kHz",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

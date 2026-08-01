#!/usr/bin/env python3
"""Build the promo-grade V2 video from captured browser frames and narration."""

from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRAMES = ROOT / "frames"
ASSETS = ROOT / "assets"
GENERATED = ROOT / "generated"
AUDIO = ROOT / "audio"


SEQUENCES = {
    "hook": ("motion-hook", 12.5),
    "loop": ("motion-loop", 12.0),
    "n8n": ("n8n", 53.0),
    "pisama": ("pisama", 44.0),
    "boundary": ("motion-boundary", 9.0),
    "evaluation": ("evaluation", 36.0),
    "close": ("motion-close", 9.5),
}


CURSORS = {
    "n8n": {
        "points": [
            (0, 420, 300),
            (3.5, 1010, 970),
            (4.2, 996, 980),
            (10.5, 900, 680),
            (11, 880, 680),
            (14.5, 1738, 140),
            (15, 1722, 132),
            (21.5, 1870, 72),
            (22, 1853, 66),
            (23.8, 1550, 580),
            (24.3, 1538, 570),
            (27.8, 1820, 140),
            (28.3, 1805, 132),
            (35.5, 1870, 72),
            (36, 1853, 66),
            (37.8, 1555, 920),
            (38.3, 1541, 912),
            (41.8, 1860, 140),
            (42.3, 1847, 132),
            (50, 1847, 132),
        ],
        "clicks": [4, 11, 15, 22, 24.3, 28.3, 36, 38.3, 42.3],
    },
    "pisama": {
        "points": [
            (0, 600, 300),
            (4.5, 1748, 610),
            (5, 1733, 600),
            (10.5, 1200, 1000),
            (11, 1200, 1000),
            (19.5, 660, 145),
            (20, 645, 135),
            (23.5, 1748, 755),
            (24, 1733, 744),
            (30.5, 1200, 1000),
            (31, 1200, 1000),
            (38.5, 690, 1000),
            (39, 675, 998),
            (44, 675, 998),
        ],
        "clicks": [5, 20, 24, 39],
    },
    "evaluation": {
        "points": [
            (0, 600, 300),
            (6.5, 1760, 190),
            (7, 1749, 180),
            (16.5, 1820, 980),
            (17, 1809, 971),
            (24.5, 1500, 1020),
            (25, 1500, 1020),
            (30, 1500, 1020),
        ],
        "clicks": [7, 17],
    },
}


SCENES = [
    ("hook", [("01-hook.wav", 0)]),
    ("loop", [("02-loop.wav", 0)]),
    (
        "n8n",
        [("03-n8n-setup.wav", 0), ("04-n8n-run.wav", 17), ("05-n8n-results.wav", 28)],
    ),
    ("pisama", [("06-pisama-timeout.wav", 0), ("07-pisama-contract.wav", 28)]),
    ("boundary", [("08-boundary.wav", 2)]),
    ("evaluation", [("09-evaluation.wav", 0), ("10-revision.wav", 25)]),
    ("close", [("11-close.wav", 1)]),
]


CALLOUTS = [
    (26.5, 33.0, "LIVE N8N RUN", "5 synthetic cases  •  2 clean  •  3 failures"),
    (67.5, 75.5, "IDEMPOTENT RERUN", "All 5 receipts return deduplicated = true"),
    (82.5, 91.0, "TIMEOUT EVIDENCE", "64.0 s observed  •  30.0 s limit"),
    (97.5, 103.5, "HUMAN REVIEW", "Useful finding, preserved with the evidence"),
    (106.5, 116.0, "CONTRACT EVIDENCE", "Required output fields are explicit"),
    (132.5, 141.0, "REVIEWED CORPUS", "19 frozen  •  18 regression  •  1 holdout"),
    (143.5, 152.0, "IMMUTABLE RUN 3", "100% recall  •  holdout excluded"),
    (155.5, 165.0, "APPEND-ONLY REVISION", "Labels and evidence stay auditable"),
]


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def ffmpeg(*args: str) -> None:
    run("ffmpeg", "-y", "-loglevel", "warning", *args)


def prepare_narration() -> None:
    for source in sorted(AUDIO.glob("*-elevenlabs.mp3")):
        destination = AUDIO / source.name.replace("-elevenlabs.mp3", ".wav")
        if (
            destination.exists()
            and destination.stat().st_mtime >= source.stat().st_mtime
        ):
            continue
        ffmpeg("-i", str(source), "-ar", "48000", "-ac", "1", str(destination))


def number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def piecewise(points: list[tuple[float, float, float]], axis: int) -> str:
    expression = number(points[-1][axis])
    for current, following in reversed(list(zip(points[:-1], points[1:]))):
        start, start_value = current[0], current[axis]
        end, end_value = following[0], following[axis]
        duration = end - start
        progress = f"(t-{number(start)})/{number(duration)}"
        segment = (
            f"{number(start_value)}+"
            f"({number(end_value)}-{number(start_value)})*{progress}"
        )
        expression = f"if(lt(t,{number(end)}),{segment},{expression})"
    return expression


def encode_sequence(name: str, source_dir: str, duration: float) -> Path:
    output = GENERATED / f"raw-{name}.mp4"
    source = FRAMES / source_dir / "frame-%05d.jpg"
    filters = "scale=1920:1080:flags=lanczos,fps=30,format=yuv420p"
    source_frame_count = len(list((FRAMES / source_dir).glob("frame-*.jpg")))
    source_duration = source_frame_count / 15
    if duration > source_duration:
        filters += (
            f",tpad=stop_mode=clone:stop_duration={number(duration - source_duration)}"
        )
    ffmpeg(
        "-framerate",
        "15",
        "-i",
        str(source),
        "-vf",
        filters,
        "-t",
        number(duration),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(output),
    )
    return output


def render_cursor(name: str, source: Path, duration: float) -> Path:
    spec = CURSORS[name]
    x = piecewise(spec["points"], 1)
    y = piecewise(spec["points"], 2)
    click_enable = "+".join(
        f"between(t,{number(moment - 0.08)},{number(moment + 0.42)})"
        for moment in spec["clicks"]
    )
    output = GENERATED / f"cursor-{name}.mp4"
    cursor_png = GENERATED / "cursor.png"
    click_png = GENERATED / "click.png"
    ffmpeg(
        "-i",
        str(source),
        "-loop",
        "1",
        "-i",
        str(cursor_png),
        "-loop",
        "1",
        "-i",
        str(click_png),
        "-filter_complex",
        (
            f"[1:v]scale=54:-1[cursor];[2:v]scale=96:-1[ring];"
            f"[0:v][cursor]overlay=x='{x}':y='{y}'[with_cursor];"
            f"[with_cursor][ring]overlay=x='{x}-22':y='{y}-20':enable='{click_enable}'[v]"
        ),
        "-map",
        "[v]",
        "-t",
        number(duration),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(output),
    )
    return output


def mux_scene(
    name: str, video: Path, audio_tracks: list[tuple[str, float]], duration: float
) -> Path:
    output = GENERATED / f"scene-{name}.mp4"
    command = ["-i", str(video)]
    for audio_name, _ in audio_tracks:
        command.extend(["-i", str(AUDIO / audio_name)])
    filters = [
        (f"[0:v]fade=t=in:st=0:d=0.25,fade=t=out:st={number(duration - 0.3)}:d=0.3[v]")
    ]
    mixed = []
    for index, (_, delay) in enumerate(audio_tracks, 1):
        label = f"a{index}"
        filters.append(
            f"[{index}:a]adelay={int(delay * 1000)}|{int(delay * 1000)}[{label}]"
        )
        mixed.append(f"[{label}]")
    audio_fades = f"afade=t=in:d=0.15,afade=t=out:st={number(duration - 0.3)}:d=0.3"
    if len(mixed) == 1:
        filters.append(f"{mixed[0]}apad,{audio_fades}[a]")
    else:
        filters.append(
            f"{''.join(mixed)}amix=inputs={len(mixed)}:duration=longest:normalize=0,"
            f"apad,{audio_fades}[a]"
        )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            number(duration),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            str(output),
        ]
    )
    ffmpeg(*command)
    return output


def render_callout_assets() -> list[Path]:
    assets = []
    for index, (_, _, label, value) in enumerate(CALLOUTS):
        svg = GENERATED / f"callout-{index}.svg"
        png = GENERATED / f"callout-{index}.png"
        svg.write_text(
            f"""<svg xmlns=\"http://www.w3.org/2000/svg\"
  width=\"880\" height=\"112\" viewBox=\"0 0 880 112\">
<rect x=\"0\" y=\"0\" width=\"880\" height=\"112\" rx=\"14\"
  fill=\"#090a09\" fill-opacity=\"0.94\"/>
<rect x=\"0\" y=\"0\" width=\"5\" height=\"112\" rx=\"2.5\"
  fill=\"#e5b84b\"/>
<text x=\"30\" y=\"38\" fill=\"#e5b84b\"
  font-family=\"Arial, sans-serif\" font-size=\"18\"
  font-weight=\"700\" letter-spacing=\"2\">{html.escape(label)}</text>
<text x=\"30\" y=\"79\" fill=\"#f4f5f0\"
  font-family=\"Georgia, serif\" font-size=\"28\">{html.escape(value)}</text>
</svg>\n""",
            encoding="utf-8",
        )
        run("sips", "-s", "format", "png", str(svg), "--out", str(png))
        assets.append(png)
    return assets


def overlay_callouts(video: Path, duration: float) -> Path:
    output = GENERATED / "captioned.mp4"
    callout_assets = render_callout_assets()
    command = ["-i", str(video)]
    for asset in callout_assets:
        command.extend(["-loop", "1", "-i", str(asset)])

    filters = []
    previous = "0:v"
    for index, (start, end, _, _) in enumerate(CALLOUTS, 1):
        output_label = f"v{index}"
        filters.append(
            f"[{previous}][{index}:v]overlay=x=72:y=916:"
            f"enable='between(t,{number(start)},{number(end)})'[{output_label}]"
        )
        previous = output_label

    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{previous}]",
            "-map",
            "0:a",
            "-t",
            number(duration),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(output),
        ]
    )
    ffmpeg(*command)
    return output


def create_sound_design(duration: float) -> tuple[Path, Path]:
    bed = GENERATED / "ambient-bed.wav"
    click = GENERATED / "ui-click.wav"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=55:sample_rate=48000:duration={number(duration)}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=82.41:sample_rate=48000:duration={number(duration)}",
        "-f",
        "lavfi",
        "-i",
        f"anoisesrc=color=pink:sample_rate=48000:duration={number(duration)}",
        "-filter_complex",
        (
            "[0:a]volume=0.010[a0];[1:a]volume=0.006[a1];"
            "[2:a]highpass=f=80,lowpass=f=360,volume=0.0025[a2];"
            f"[a0][a1][a2]amix=inputs=3:normalize=0,"
            f"afade=t=in:st=0:d=2,afade=t=out:st={number(duration - 4)}:d=4[bed]"
        ),
        "-map",
        "[bed]",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(bed),
    )
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1450:sample_rate=48000:duration=0.055",
        "-af",
        "volume=0.12,afade=t=out:st=0.012:d=0.043",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(click),
    )
    return bed, click


def add_sound_design(video: Path, duration: float) -> Path:
    output = ROOT / "pisama-closed-loop-promo-v2.mp4"
    bed, click = create_sound_design(duration)
    scene_starts = {"n8n": 24.5, "pisama": 77.5, "evaluation": 130.5}
    click_moments = [
        scene_starts[scene] + moment
        for scene in ("n8n", "pisama", "evaluation")
        for moment in CURSORS[scene]["clicks"]
    ]
    split_outputs = "".join(f"[c{index}]" for index in range(len(click_moments)))
    filters = [
        "[0:a]volume=1.0[voice]",
        "[1:a]volume=1.0[bed]",
        f"[2:a]asplit={len(click_moments)}{split_outputs}",
    ]
    delayed = []
    for index, moment in enumerate(click_moments):
        label = f"d{index}"
        delay = int(moment * 1000)
        filters.append(f"[c{index}]adelay={delay}|{delay}[{label}]")
        delayed.append(f"[{label}]")
    filters.append(
        f"[voice][bed]{''.join(delayed)}"
        f"amix=inputs={2 + len(delayed)}:duration=first:normalize=0,"
        "loudnorm=I=-16:TP=-1.5:LRA=11[a]"
    )
    ffmpeg(
        "-i",
        str(video),
        "-i",
        str(bed),
        "-i",
        str(click),
        "-filter_complex",
        ";".join(filters),
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-t",
        number(duration),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(output),
    )
    return output


def main() -> int:
    GENERATED.mkdir(parents=True, exist_ok=True)
    prepare_narration()
    for asset in ("cursor", "click"):
        run(
            "sips",
            "-s",
            "format",
            "png",
            str(ASSETS / f"{asset}.svg"),
            "--out",
            str(GENERATED / f"{asset}.png"),
        )

    raw = {
        name: encode_sequence(name, source_dir, duration)
        for name, (source_dir, duration) in SEQUENCES.items()
    }
    visuals = dict(raw)
    for name in CURSORS:
        visuals[name] = render_cursor(name, raw[name], SEQUENCES[name][1])

    scene_files = []
    for name, tracks in SCENES:
        scene_files.append(mux_scene(name, visuals[name], tracks, SEQUENCES[name][1]))

    concat_path = GENERATED / "concat.txt"
    concat_path.write_text(
        "".join(f"file '{scene.name}'\n" for scene in scene_files), encoding="utf-8"
    )
    draft = ROOT / "pisama-closed-loop-promo-v2-draft.mp4"
    ffmpeg(
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        str(draft),
    )
    duration = sum(item[1] for item in SEQUENCES.values())
    captioned = overlay_callouts(draft, duration)
    output = add_sound_design(captioned, duration)
    print(
        json.dumps({"output": str(output), "scenes": len(scene_files)}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

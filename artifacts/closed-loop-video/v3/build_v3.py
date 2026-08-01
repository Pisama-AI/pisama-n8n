#!/usr/bin/env python3
"""Build the image-led PISAMA Closed Reliability Loop promo."""

from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
AUDIO = ROOT / "audio"
GENERATED = ROOT / "generated"
LOOP_IMAGE = ASSETS / "pisama-reliability-loop.png"
BUMPER_DURATION = 2.5


STAGE_CROPS = {
    "setup": (822, 545, 756, 291),
    "execution": (1551, 936, 759, 291),
    "evidence": (1551, 1495, 759, 291),
    "diagnose": (822, 1885, 756, 290),
    "verify": (90, 1495, 760, 291),
    "prevent": (90, 936, 760, 291),
}


STAGES = [
    {
        "key": "setup",
        "number": "01",
        "source": "n8n-product.mp4",
        "source_start": 0.0,
        "source_duration": 19.0,
        "duration": 19.0,
        "audio": "02-setup.wav",
        "label": "CONTROL DESIGN",
        "value": "5 synthetic cases  •  2 clean  •  3 failed",
    },
    {
        "key": "execution",
        "number": "02",
        "source": "n8n-product.mp4",
        "source_start": 17.0,
        "source_duration": 19.0,
        "duration": 19.0,
        "audio": "03-execution.wav",
        "label": "LIVE N8N EXECUTION",
        "value": "Evaluate every trace  •  retain stable identity",
    },
    {
        "key": "evidence",
        "number": "03",
        "source": "n8n-product.mp4",
        "source_start": 29.0,
        "source_duration": 24.0,
        "duration": 24.0,
        "audio": "04-evidence.wav",
        "label": "STABLE EVIDENCE",
        "value": "Expected = actual  •  repeat run deduplicated",
    },
    {
        "key": "diagnose",
        "number": "04",
        "source": "pisama-product.mp4",
        "source_start": 0.0,
        "source_duration": 44.0,
        "duration": 27.5,
        "audio": "05-diagnose.wav",
        "label": "RETAINED FAILURE EVIDENCE",
        "value": "64.0 s observed  •  30.0 s limit  •  human verdict",
    },
    {
        "key": "verify",
        "number": "05",
        "source": "evaluation-product.mp4",
        "source_start": 0.0,
        "source_duration": 36.0,
        "duration": 27.5,
        "audio": "06-verify.wav",
        "label": "IMMUTABLE RELEASE GATE",
        "value": "19 reviewed  •  18 regression  •  1 holdout",
    },
    {
        "key": "prevent",
        "number": "06",
        "source": "prevent-product.mp4",
        "source_start": 0.0,
        "source_duration": 30.0,
        "duration": 27.5,
        "audio": "07-prevent.wav",
        "label": "TWO REAL PREVENTION PROBES",
        "value": "Malformed rejected  •  valid passed  •  rollback retained",
    },
]


PREVENT_CURSOR = [
    (0.0, 1050, 250),
    (5.0, 1000, 350),
    (10.0, 780, 570),
    (14.0, 620, 845),
    (18.0, 900, 600),
    (23.0, 1100, 760),
    (27.5, 730, 820),
]


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def ffmpeg(*args: str) -> None:
    run("ffmpeg", "-y", "-loglevel", "warning", *args)


def number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def prepare_audio() -> None:
    for source in sorted(AUDIO.glob("*-elevenlabs.mp3")):
        destination = AUDIO / source.name.replace("-elevenlabs.mp3", ".wav")
        if (
            destination.exists()
            and destination.stat().st_mtime >= source.stat().st_mtime
        ):
            continue
        ffmpeg("-i", str(source), "-ar", "48000", "-ac", "1", str(destination))


def write_svg(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    output = path.with_suffix(".png")
    run("sips", "-s", "format", "png", str(path), "--out", str(output))
    return output


def render_static_assets() -> dict[str, Path]:
    GENERATED.mkdir(parents=True, exist_ok=True)
    grid = write_svg(
        GENERATED / "grid.svg",
        """<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080">
<defs><pattern id="g" width="24" height="24" patternUnits="userSpaceOnUse">
<path d="M 24 0 L 0 0 0 24" fill="none" stroke="#1a1e1a" stroke-width="1"/>
</pattern></defs>
<rect width="1920" height="1080" fill="#0b0d0b"/>
<rect width="1920" height="1080" fill="url(#g)"/>
</svg>\n""",
    )
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

    canvas = GENERATED / "loop-canvas.png"
    ffmpeg(
        "-i",
        str(grid),
        "-i",
        str(LOOP_IMAGE),
        "-filter_complex",
        "[1:v]scale=1080:1080:flags=lanczos[loop];[0:v][loop]overlay=420:0[v]",
        "-map",
        "[v]",
        "-frames:v",
        "1",
        str(canvas),
    )

    crops = {}
    for key, (x, y, width, height) in STAGE_CROPS.items():
        output = GENERATED / f"stage-{key}.png"
        ffmpeg(
            "-i",
            str(LOOP_IMAGE),
            "-vf",
            f"crop={width}:{height}:{x}:{y}",
            "-frames:v",
            "1",
            str(output),
        )
        crops[key] = output
    return {"grid": grid, "canvas": canvas, **crops}


def render_progress(stage_index: int) -> Path:
    dots = []
    for index in range(6):
        x = 30 + index * 108
        color = "#e9ad28" if index <= stage_index else "#4b4a43"
        radius = 8 if index == stage_index else 5
        dots.append(f'<circle cx="{x}" cy="20" r="{radius}" fill="{color}"/>')
    return write_svg(
        GENERATED / f"progress-{stage_index + 1}.svg",
        """<svg xmlns="http://www.w3.org/2000/svg" width="600" height="40">
<line x1="30" y1="20" x2="570" y2="20" stroke="#4b4a43" stroke-width="2"/>
"""
        + "".join(dots)
        + "\n</svg>\n",
    )


def render_callout(stage: dict[str, object]) -> Path:
    label = html.escape(str(stage["label"]))
    value = html.escape(str(stage["value"]))
    return write_svg(
        GENERATED / f"callout-{stage['key']}.svg",
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="112">
<rect width="1120" height="112" rx="10" fill="#0b0d0b" fill-opacity="0.94"/>
<rect width="5" height="112" rx="2.5" fill="#e9ad28"/>
<text x="30" y="38" fill="#e9ad28" font-family="Arial, sans-serif"
  font-size="18" font-weight="700" letter-spacing="2">{label}</text>
<text x="30" y="80" fill="#f3efe4" font-family="Georgia, serif"
  font-size="30">{value}</text>
</svg>\n""",
    )


def piecewise(points: list[tuple[float, float, float]], axis: int) -> str:
    expression = number(points[-1][axis])
    for current, following in reversed(list(zip(points[:-1], points[1:]))):
        start, start_value = current[0], current[axis]
        end, end_value = following[0], following[axis]
        progress = f"(t-{number(start)})/{number(end - start)}"
        segment = (
            f"{number(start_value)}+"
            f"({number(end_value)}-{number(start_value)})*{progress}"
        )
        expression = f"if(lt(t,{number(end)}),{segment},{expression})"
    return expression


def render_loop_scene(canvas: Path, name: str, duration: float, closing: bool) -> Path:
    output = GENERATED / f"visual-{name}.mp4"
    if closing:
        zoom = "min(1.08,1.0+on*0.000141)"
    else:
        zoom = "max(1.0,1.10-on*0.00019)"
    filters = (
        f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps=30,"
        f"fade=t=in:st=0:d=0.4,"
        f"fade=t=out:st={number(duration - 0.5)}:d=0.5,format=yuv420p"
    )
    ffmpeg(
        "-framerate",
        "30",
        "-loop",
        "1",
        "-i",
        str(canvas),
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
        "-an",
        str(output),
    )
    return output


def render_bumper(
    stage: dict[str, object], assets: dict[str, Path], index: int
) -> Path:
    output = GENERATED / f"bumper-{stage['key']}.mp4"
    progress = render_progress(index)
    ffmpeg(
        "-framerate",
        "30",
        "-loop",
        "1",
        "-i",
        str(assets["grid"]),
        "-framerate",
        "30",
        "-loop",
        "1",
        "-i",
        str(assets[str(stage["key"])]),
        "-framerate",
        "30",
        "-loop",
        "1",
        "-i",
        str(progress),
        "-filter_complex",
        (
            "[1:v]scale=1100:-1:flags=lanczos[card];"
            "[0:v][card]overlay=(W-w)/2:(H-h)/2-35[base];"
            "[2:v]scale=600:40[progress];"
            "[base][progress]overlay=(W-w)/2:875,"
            "fade=t=in:st=0:d=0.25,fade=t=out:st=2.2:d=0.3[v]"
        ),
        "-map",
        "[v]",
        "-t",
        number(BUMPER_DURATION),
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


def render_product(stage: dict[str, object]) -> Path:
    key = str(stage["key"])
    output = GENERATED / f"product-{key}.mp4"
    speed = float(stage["source_duration"]) / float(stage["duration"])
    source = ASSETS / str(stage["source"])
    command = [
        "-ss",
        number(float(stage["source_start"])),
        "-t",
        number(float(stage["source_duration"])),
        "-i",
        str(source),
    ]
    filters = f"setpts=PTS/{number(speed)},fps=30"
    if key == "prevent":
        x = piecewise(PREVENT_CURSOR, 1)
        y = piecewise(PREVENT_CURSOR, 2)
        command.extend(["-loop", "1", "-i", str(GENERATED / "cursor.png")])
        filters = (
            f"[0:v]setpts=PTS/{number(speed)},fps=30[base];"
            "[1:v]scale=48:-1[cursor];"
            f"[base][cursor]overlay=x='{x}':y='{y}'[v]"
        )
        command.extend(["-filter_complex", filters, "-map", "[v]"])
    else:
        command.extend(["-vf", filters])
    command.extend(
        [
            "-t",
            number(float(stage["duration"])),
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
        ]
    )
    ffmpeg(*command)
    return output


def wrap_product(
    stage: dict[str, object],
    product: Path,
    assets: dict[str, Path],
) -> Path:
    output = GENERATED / f"wrapped-{stage['key']}.mp4"
    callout = render_callout(stage)
    duration = float(stage["duration"])
    ffmpeg(
        "-framerate",
        "30",
        "-loop",
        "1",
        "-i",
        str(assets["grid"]),
        "-i",
        str(product),
        "-framerate",
        "30",
        "-loop",
        "1",
        "-i",
        str(assets[str(stage["key"])]),
        "-framerate",
        "30",
        "-loop",
        "1",
        "-i",
        str(LOOP_IMAGE),
        "-framerate",
        "30",
        "-loop",
        "1",
        "-i",
        str(callout),
        "-filter_complex",
        (
            "[1:v]scale=1500:844:flags=lanczos[product];"
            "[0:v][product]overlay=380:86[base];"
            "[base]drawbox=x=379:y=85:w=1502:h=846:"
            "color=0x3a3a31:t=1[framed];"
            "[2:v]scale=340:-1:flags=lanczos[card];"
            "[framed][card]overlay=18:92[with_card];"
            "[3:v]scale=300:300:flags=lanczos,format=rgba,"
            "colorchannelmixer=aa=0.42[map];"
            "[with_card][map]overlay=36:470[with_map];"
            "[4:v]scale=1120:112[callout];"
            "[with_map][callout]overlay=410:800,"
            f"fade=t=in:st=0:d=0.25,"
            f"fade=t=out:st={number(duration - 0.3)}:d=0.3[v]"
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


def concat_video(parts: list[Path], output: Path) -> Path:
    manifest = output.with_suffix(".txt")
    manifest.write_text(
        "".join(f"file '{part.name}'\n" for part in parts),
        encoding="utf-8",
    )
    ffmpeg(
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(manifest),
        "-c:v",
        "copy",
        "-an",
        str(output),
    )
    return output


def mux_narration(
    video: Path,
    audio: Path,
    output: Path,
    duration: float,
    delay: float,
) -> Path:
    milliseconds = int(delay * 1000)
    ffmpeg(
        "-i",
        str(video),
        "-i",
        str(audio),
        "-filter_complex",
        f"[1:a]adelay={milliseconds}|{milliseconds},apad[a]",
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
        "192k",
        "-ar",
        "48000",
        str(output),
    )
    return output


def add_sound_design(video: Path, duration: float) -> Path:
    output = ROOT / "pisama-closed-reliability-loop-v3.mp4"
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
            "[0:a]volume=0.009[a0];[1:a]volume=0.005[a1];"
            "[2:a]highpass=f=80,lowpass=f=360,volume=0.002[a2];"
            f"[a0][a1][a2]amix=inputs=3:normalize=0,"
            f"afade=t=in:st=0:d=2,"
            f"afade=t=out:st={number(duration - 4)}:d=4[bed]"
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
        "volume=0.11,afade=t=out:st=0.012:d=0.043",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(click),
    )

    click_moments = [
        24.0,
        31.0,
        35.0,
        46.5,
        48.8,
        52.8,
        70.0,
        72.3,
        76.3,
        92.625,
        102.0,
        104.5,
        113.875,
        124.847,
        132.486,
    ]
    split_outputs = "".join(f"[c{index}]" for index in range(len(click_moments)))
    filters = [
        "[0:a]volume=1.0,pan=stereo|c0=c0|c1=c0[voice]",
        "[1:a]volume=1.0[bed]",
        f"[2:a]asplit={len(click_moments)}{split_outputs}",
    ]
    delayed = []
    for index, moment in enumerate(click_moments):
        label = f"d{index}"
        milliseconds = int(moment * 1000)
        filters.append(f"[c{index}]adelay={milliseconds}|{milliseconds}[{label}]")
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
        "-i",
        str(ROOT / "captions.srt"),
        "-filter_complex",
        ";".join(filters),
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-map",
        "3:0",
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
        "-c:s",
        "mov_text",
        "-metadata:s:s:0",
        "language=eng",
        "-disposition:s:0",
        "default",
        "-movflags",
        "+faststart",
        str(output),
    )
    return output


def main() -> int:
    prepare_audio()
    assets = render_static_assets()
    scenes = []

    intro_duration = 17.5
    intro_visual = render_loop_scene(assets["canvas"], "intro", intro_duration, False)
    scenes.append(
        mux_narration(
            intro_visual,
            AUDIO / "01-overview.wav",
            GENERATED / "scene-intro.mp4",
            intro_duration,
            0.0,
        )
    )

    for index, stage in enumerate(STAGES):
        bumper = render_bumper(stage, assets, index)
        product = render_product(stage)
        wrapped = wrap_product(stage, product, assets)
        group_duration = BUMPER_DURATION + float(stage["duration"])
        group_video = concat_video(
            [bumper, wrapped], GENERATED / f"group-{stage['key']}.mp4"
        )
        scenes.append(
            mux_narration(
                group_video,
                AUDIO / str(stage["audio"]),
                GENERATED / f"scene-{stage['key']}.mp4",
                group_duration,
                0.7,
            )
        )

    close_duration = 19.0
    close_visual = render_loop_scene(assets["canvas"], "close", close_duration, True)
    scenes.append(
        mux_narration(
            close_visual,
            AUDIO / "08-close.wav",
            GENERATED / "scene-close.mp4",
            close_duration,
            0.2,
        )
    )

    draft = ROOT / "pisama-closed-reliability-loop-v3-draft.mp4"
    manifest = GENERATED / "master-concat.txt"
    manifest.write_text(
        "".join(f"file '{scene.name}'\n" for scene in scenes),
        encoding="utf-8",
    )
    ffmpeg(
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(manifest),
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
    duration = (
        intro_duration
        + close_duration
        + sum(BUMPER_DURATION + float(stage["duration"]) for stage in STAGES)
    )
    output = add_sound_design(draft, duration)
    print(
        json.dumps(
            {"duration": duration, "output": str(output), "stages": len(STAGES)},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

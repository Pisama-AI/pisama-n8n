#!/usr/bin/env python3
"""Build the evidence-led PISAMA closed reliability loop promo."""

from __future__ import annotations

import html
import json
import re
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
AUDIO = ROOT / "audio"
FRAMES = ROOT / "frames"
GENERATED = ROOT / "generated"
LOOP_IMAGE = ASSETS / "pisama-reliability-loop.png"

FPS = 30
VOICE_SPEED = 1.03
VOICE_DELAY = 0.25
SCENE_TAIL = 0.55
BUMPER_DURATION = 0.9

X264 = [
    "-c:v",
    "libx264",
    "-preset",
    "slow",
    "-crf",
    "17",
    "-pix_fmt",
    "yuv420p",
    "-color_range",
    "tv",
    "-color_primaries",
    "bt709",
    "-color_trc",
    "bt709",
    "-colorspace",
    "bt709",
    "-x264-params",
    "colorprim=bt709:transfer=bt709:colormatrix=bt709",
]

STAGE_CROPS = {
    "setup": (822, 545, 756, 291),
    "execution": (1551, 936, 759, 291),
    "evidence": (1551, 1495, 759, 291),
    "diagnose": (822, 1885, 756, 290),
    "verify": (90, 1495, 760, 291),
    "prevent": (90, 936, 760, 291),
}


@dataclass(frozen=True)
class Scene:
    key: str
    title: str
    audio: str
    callout: str


SCENES = [
    Scene(
        "hook",
        "THE RELIABILITY PROBLEM",
        "01-hook-elevenlabs.mp3",
        "A red node is visible. Recurrence is the real risk.",
    ),
    Scene(
        "loop",
        "THE CLOSED RELIABILITY LOOP",
        "02-loop-elevenlabs.mp3",
        "Detect. Heal. Verify. Prevent.",
    ),
    Scene(
        "setup-execution",
        "01 SETUP  /  02 EXECUTION",
        "03-setup-execution-elevenlabs.mp3",
        "19 source-backed executions  ·  stable case identity",
    ),
    Scene(
        "evidence",
        "03 EVIDENCE",
        "04-evidence-elevenlabs.mp3",
        "Missing body.required.value  ·  retained with the trace",
    ),
    Scene(
        "diagnose",
        "04 DETECT + HEAL",
        "05-diagnose-elevenlabs.mp3",
        "64.0 s observed  ·  30.0 s limit  ·  human reviewed",
    ),
    Scene(
        "verify",
        "05 VERIFY",
        "06-verify-elevenlabs.mp3",
        "18 regression cases  ·  1 sealed holdout  ·  100% match",
    ),
    Scene(
        "prevent",
        "06 PREVENT",
        "07-prevent-elevenlabs.mp3",
        "Malformed rejected  ·  valid passed  ·  rollback retained",
    ),
    Scene(
        "close",
        "CLOSE THE RELIABILITY LOOP",
        "08-close-elevenlabs.mp3",
        "See what failed. Prove the fix. Prevent recurrence.",
    ),
]


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def ffmpeg(*args: str) -> None:
    run("ffmpeg", "-y", "-loglevel", "warning", *args)


def number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def duration(path: Path) -> float:
    return float(
        run(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
            capture=True,
        )
    )


def svg_to_png(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    output = path.with_suffix(".png")
    run("sips", "-s", "format", "png", str(path), "--out", str(output))
    return output


def encode_captures() -> None:
    for key in ("n8n", "evidence", "diagnose", "verify", "prevent"):
        output = ASSETS / f"{key}-capture.mp4"
        if output.exists():
            continue
        source = FRAMES / key / "frame-%05d.jpg"
        ffmpeg(
            "-framerate",
            "10",
            "-i",
            str(source),
            "-vf",
            f"scale=1920:1080:flags=lanczos,fps={FPS},setsar=1,format=yuv420p",
            *X264,
            "-an",
            "-movflags",
            "+faststart",
            str(output),
        )


def prepare_audio() -> dict[str, float]:
    values = {}
    for scene in SCENES:
        source = AUDIO / scene.audio
        destination = AUDIO / scene.audio.replace("-elevenlabs.mp3", ".wav")
        ffmpeg(
            "-i",
            str(source),
            "-af",
            f"atempo={number(VOICE_SPEED)}",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(destination),
        )
        values[scene.key] = duration(destination)
    return values


def render_design_assets() -> dict[str, Path]:
    GENERATED.mkdir(parents=True, exist_ok=True)
    grid = svg_to_png(
        GENERATED / "grid.svg",
        """<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080">
<defs><pattern id="g" width="32" height="32" patternUnits="userSpaceOnUse">
<path d="M 32 0 L 0 0 0 32" fill="none" stroke="#20231f" stroke-width="1"/>
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
        "[1:v]scale=1080:1080:flags=lanczos[loop];[0:v][loop]overlay=(W-w)/2:0[v]",
        "-map",
        "[v]",
        "-frames:v",
        "1",
        str(canvas),
    )

    assets: dict[str, Path] = {"grid": grid, "canvas": canvas}
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
        assets[key] = output
    return assets


def render_label(name: str, eyebrow: str, body: str, width: int = 1320) -> Path:
    safe_eyebrow = html.escape(eyebrow)
    safe_body = html.escape(body)
    return svg_to_png(
        GENERATED / f"label-{name}.svg",
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="114">
<rect width="{width}" height="114" rx="12" fill="#0b0d0b" fill-opacity="0.93"/>
<rect width="6" height="114" rx="3" fill="#e9ad28"/>
<text x="34" y="40" fill="#e9ad28" font-family="Arial, sans-serif"
 font-size="19" font-weight="700" letter-spacing="2">{safe_eyebrow}</text>
<text x="34" y="83" fill="#f4efe2" font-family="Georgia, serif"
 font-size="30">{safe_body}</text>
</svg>\n""",
    )


def render_chip(scene: Scene) -> Path:
    title = html.escape(scene.title)
    return svg_to_png(
        GENERATED / f"chip-{scene.key}.svg",
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="530" height="58">
<rect width="530" height="58" rx="9" fill="#0b0d0b" fill-opacity="0.92"/>
<circle cx="28" cy="29" r="7" fill="#e9ad28"/>
<text x="51" y="36" fill="#f4efe2" font-family="Arial, sans-serif"
 font-size="19" font-weight="700" letter-spacing="1.7">{title}</text>
</svg>\n""",
    )


def render_bumper(key: str, index: int, assets: dict[str, Path]) -> Path:
    output = GENERATED / f"bumper-{key}.mp4"
    dots = []
    for position in range(6):
        x = 22 + position * 86
        color = "#e9ad28" if position <= index else "#55544c"
        radius = 8 if position == index else 5
        dots.append(f'<circle cx="{x}" cy="18" r="{radius}" fill="{color}"/>')
    progress = svg_to_png(
        GENERATED / f"progress-{key}.svg",
        """<svg xmlns="http://www.w3.org/2000/svg" width="474" height="36">
<line x1="22" y1="18" x2="452" y2="18" stroke="#55544c" stroke-width="2"/>
"""
        + "".join(dots)
        + "\n</svg>\n",
    )
    ffmpeg(
        "-framerate",
        str(FPS),
        "-loop",
        "1",
        "-i",
        str(assets["grid"]),
        "-framerate",
        str(FPS),
        "-loop",
        "1",
        "-i",
        str(assets[key]),
        "-framerate",
        str(FPS),
        "-loop",
        "1",
        "-i",
        str(progress),
        "-filter_complex",
        (
            "[1:v]scale=1110:-1:flags=lanczos[card];"
            "[0:v][card]overlay=(W-w)/2:(H-h)/2-34[base];"
            "[2:v]scale=474:36[progress];"
            "[base][progress]overlay=(W-w)/2:842,"
            "fade=t=in:st=0:d=0.12,fade=t=out:st=0.72:d=0.18[v]"
        ),
        "-map",
        "[v]",
        "-t",
        number(BUMPER_DURATION),
        *X264,
        "-an",
        str(output),
    )
    return output


def render_capture_segment(
    key: str,
    name: str,
    source_start: float,
    source_duration: float,
    output_duration: float,
    cursor: bool = False,
) -> Path:
    output = GENERATED / f"capture-{name}.mp4"
    source = ASSETS / f"{key}-capture.mp4"
    speed = source_duration / output_duration
    command = [
        "-ss",
        number(source_start),
        "-t",
        number(source_duration),
        "-i",
        str(source),
    ]
    if cursor:
        command.extend(["-loop", "1", "-i", str(GENERATED / "cursor.png")])
        x = "if(lt(t,2.6),1400-250*t,if(lt(t,5.5),750+140*(t-2.6),1150))"
        y = "if(lt(t,2.6),150+245*t,if(lt(t,5.5),790-75*(t-2.6),570))"
        filters = (
            f"[0:v]setpts=PTS/{number(speed)},fps={FPS}[base];"
            "[1:v]scale=52:-1[cursor];"
            f"[base][cursor]overlay=x='{x}':y='{y}'[v]"
        )
        command.extend(["-filter_complex", filters, "-map", "[v]"])
    else:
        command.extend(["-vf", f"setpts=PTS/{number(speed)},fps={FPS}"])
    command.extend(
        [
            "-t",
            number(output_duration),
            *X264,
            "-an",
            str(output),
        ]
    )
    ffmpeg(*command)
    return output


def concat_video(parts: list[Path], output: Path) -> Path:
    manifest = output.with_suffix(".txt")
    manifest.write_text(
        "".join(f"file '{part.name}'\n" for part in parts), encoding="utf-8"
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


def decorate_product(scene: Scene, product: Path, scene_duration: float) -> Path:
    output = GENERATED / f"visual-{scene.key}.mp4"
    chip = render_chip(scene)
    label = render_label(scene.key, "VERIFIED PRODUCT EVIDENCE", scene.callout)
    label_end = min(5.2, scene_duration - 0.3)
    ffmpeg(
        "-i",
        str(product),
        "-loop",
        "1",
        "-i",
        str(chip),
        "-loop",
        "1",
        "-i",
        str(label),
        "-filter_complex",
        (
            "[0:v]setsar=1[base];"
            "[1:v]format=rgba[chip];"
            "[base][chip]overlay=36:30[with_chip];"
            "[2:v]format=rgba,fade=t=in:st=0:d=0.18:alpha=1,"
            f"fade=t=out:st={number(label_end - 0.28)}:d=0.28:alpha=1[label];"
            f"[with_chip][label]overlay=48:H-h-44:enable='lt(t,{number(label_end)})'[v]"
        ),
        "-map",
        "[v]",
        "-t",
        number(scene_duration),
        *X264,
        "-an",
        str(output),
    )
    return output


def render_hook(scene_duration: float) -> Path:
    first_duration = scene_duration / 2
    second_duration = scene_duration - first_duration
    evidence = render_capture_segment(
        "evidence", "hook-failure", 0, 7.4, first_duration
    )
    prevention = render_capture_segment(
        "prevent", "hook-control", 18.0, 9.0, second_duration, cursor=True
    )
    first_label = render_label(
        "hook-failure", "FAILURE CAPTURED", "Missing body.required.value"
    )
    second_label = render_label(
        "hook-control",
        "CONTROL VERIFIED",
        "Malformed rejected  ·  valid passed  ·  rollback retained",
    )

    decorated = []
    for name, source, label, length in (
        ("hook-a", evidence, first_label, first_duration),
        ("hook-b", prevention, second_label, second_duration),
    ):
        output = GENERATED / f"{name}.mp4"
        ffmpeg(
            "-i",
            str(source),
            "-loop",
            "1",
            "-i",
            str(label),
            "-filter_complex",
            (
                "[1:v]format=rgba[label];"
                "[0:v][label]overlay=48:H-h-44,"
                "fade=t=in:st=0:d=0.2,"
                f"fade=t=out:st={number(length - 0.2)}:d=0.2[v]"
            ),
            "-map",
            "[v]",
            "-t",
            number(length),
            *X264,
            "-an",
            str(output),
        )
        decorated.append(output)
    return concat_video(decorated, GENERATED / "visual-hook.mp4")


def render_close_cta() -> Path:
    return svg_to_png(
        GENERATED / "close-cta.svg",
        """<svg xmlns="http://www.w3.org/2000/svg" width="360" height="250">
<rect width="360" height="250" rx="12" fill="#0b0d0b" fill-opacity="0.92"/>
<rect width="6" height="250" rx="3" fill="#e9ad28"/>
<text x="32" y="46" fill="#e9ad28" font-family="Arial, sans-serif"
 font-size="18" font-weight="700" letter-spacing="2">PISAMA.AI</text>
<text x="32" y="102" fill="#f4efe2" font-family="Georgia, serif"
 font-size="29">See what failed.</text>
<text x="32" y="144" fill="#f4efe2" font-family="Georgia, serif"
 font-size="29">Prove the fix.</text>
<text x="32" y="186" fill="#f4efe2" font-family="Georgia, serif"
 font-size="29">Prevent recurrence.</text>
</svg>\n""",
    )


def render_loop_scene(key: str, scene_duration: float, closing: bool) -> Path:
    output = GENERATED / f"visual-{key}.mp4"
    zoom = "min(1.075,1.0+on*0.00012)" if closing else "max(1.0,1.08-on*0.00016)"
    filters = (
        f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps={FPS},"
        "fade=t=in:st=0:d=0.35,"
        f"fade=t=out:st={number(scene_duration - 0.45)}:d=0.45,format=yuv420p"
    )
    if closing:
        cta = render_close_cta()
        ffmpeg(
            "-framerate",
            str(FPS),
            "-loop",
            "1",
            "-i",
            str(GENERATED / "loop-canvas.png"),
            "-loop",
            "1",
            "-i",
            str(cta),
            "-filter_complex",
            (
                f"[0:v]{filters}[base];"
                "[1:v]format=rgba,fade=t=in:st=3.5:d=0.5:alpha=1[cta];"
                "[base][cta]overlay=36:780[v]"
            ),
            "-map",
            "[v]",
            "-t",
            number(scene_duration),
            *X264,
            "-an",
            str(output),
        )
    else:
        ffmpeg(
            "-framerate",
            str(FPS),
            "-loop",
            "1",
            "-i",
            str(GENERATED / "loop-canvas.png"),
            "-vf",
            filters,
            "-t",
            number(scene_duration),
            *X264,
            "-an",
            str(output),
        )
    return output


def render_setup_execution(scene_duration: float, assets: dict[str, Path]) -> Path:
    product_time = scene_duration - 2 * BUMPER_DURATION
    first_time = min(8.2, product_time * 0.43)
    second_time = product_time - first_time
    parts = [
        render_bumper("setup", 0, assets),
        render_capture_segment("n8n", "setup", 0, 9.0, first_time, cursor=True),
        render_bumper("execution", 1, assets),
        render_capture_segment("n8n", "execution", 9.0, 15.0, second_time, cursor=True),
    ]
    product = concat_video(parts, GENERATED / "product-setup-execution.mp4")
    return decorate_product(SCENES[2], product, scene_duration)


def render_stage_scene(
    scene: Scene,
    stage_key: str,
    stage_index: int,
    scene_duration: float,
    assets: dict[str, Path],
) -> Path:
    product_duration = scene_duration - BUMPER_DURATION
    capture_source = ASSETS / f"{stage_key}-capture.mp4"
    source_duration = duration(capture_source)
    capture = render_capture_segment(
        stage_key,
        stage_key,
        0,
        source_duration,
        product_duration,
        cursor=stage_key in {"verify", "prevent"},
    )
    product = concat_video(
        [render_bumper(stage_key, stage_index, assets), capture],
        GENERATED / f"product-{stage_key}.mp4",
    )
    return decorate_product(scene, product, scene_duration)


def mux_scene(scene: Scene, visual: Path, scene_duration: float) -> Path:
    output = GENERATED / f"scene-{scene.key}.mp4"
    voice = AUDIO / scene.audio.replace("-elevenlabs.mp3", ".wav")
    delay = int(VOICE_DELAY * 1000)
    ffmpeg(
        "-i",
        str(visual),
        "-i",
        str(voice),
        "-filter_complex",
        f"[1:a]adelay={delay},apad=whole_dur={number(scene_duration)}[voice]",
        "-map",
        "0:v",
        "-map",
        "[voice]",
        "-t",
        number(scene_duration),
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


def srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def caption_lines(sentence: str) -> str:
    return "\n".join(textwrap.wrap(sentence, width=42, break_long_words=False))


def caption_chunks(sentence: str) -> list[str]:
    words = sentence.split()
    chunks = []
    while words:
        limit = min(11, len(words))
        while limit > 1 and len(" ".join(words[:limit])) > 78:
            limit -= 1
        if 0 < len(words) - limit < 4:
            limit = len(words) - 4
        for position in range(limit - 1, 4, -1):
            enough_words_remain = len(words) - position >= 4
            if enough_words_remain and words[position - 1].endswith((",", ";", ":")):
                limit = position
                break
        chunks.append(" ".join(words[:limit]))
        words = words[limit:]
    return chunks


def write_captions(
    scene_starts: dict[str, float], audio_durations: dict[str, float]
) -> None:
    entries = []
    index = 1
    for scene in SCENES:
        text = (
            (ROOT / "narration" / scene.audio.replace("-elevenlabs.mp3", ".txt"))
            .read_text(encoding="utf-8")
            .strip()
        )
        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item]
        chunks = [chunk for sentence in sentences for chunk in caption_chunks(sentence)]
        weights = [max(1, len(item.split())) for item in chunks]
        available = audio_durations[scene.key]
        cursor = scene_starts[scene.key] + VOICE_DELAY
        for chunk, weight in zip(chunks, weights, strict=True):
            item_duration = available * weight / sum(weights)
            end = cursor + item_duration - 0.06
            entries.append(
                f"{index}\n{srt_time(cursor)} --> {srt_time(end)}\n"
                f"{caption_lines(chunk)}\n"
            )
            cursor += item_duration
            index += 1
    (ROOT / "captions.srt").write_text("\n".join(entries), encoding="utf-8")


def concat_scenes(scenes: list[Path]) -> Path:
    output = GENERATED / "master-voice.mp4"
    manifest = GENERATED / "master-concat.txt"
    manifest.write_text(
        "".join(f"file '{scene.name}'\n" for scene in scenes), encoding="utf-8"
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
        str(output),
    )
    return output


def mix_master(master: Path, total_duration: float) -> Path:
    bed = GENERATED / "ambient-bed.wav"
    click = GENERATED / "ui-click.wav"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=55:sample_rate=48000:duration={number(total_duration)}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=82.41:sample_rate=48000:duration={number(total_duration)}",
        "-f",
        "lavfi",
        "-i",
        f"anoisesrc=color=pink:sample_rate=48000:duration={number(total_duration)}",
        "-filter_complex",
        (
            "[0:a]volume=0.006[a0];[1:a]volume=0.0035[a1];"
            "[2:a]highpass=f=80,lowpass=f=360,volume=0.0014[a2];"
            "[a0][a1][a2]amix=inputs=3:normalize=0,"
            "afade=t=in:st=0:d=1.5,"
            f"afade=t=out:st={number(total_duration - 3)}:d=3[bed]"
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
        "sine=frequency=1380:sample_rate=48000:duration=0.06",
        "-af",
        "volume=0.08,afade=t=out:st=0.014:d=0.046",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(click),
    )

    click_moments = [27.0, 35.5, 91.0, 116.0, 124.5]
    split = "".join(f"[c{index}]" for index in range(len(click_moments)))
    filters = [
        "[0:a]pan=stereo|c0=c0|c1=c0[voice]",
        "[1:a]volume=1.0[bed]",
        f"[2:a]asplit={len(click_moments)}{split}",
    ]
    delayed = []
    for index, moment in enumerate(click_moments):
        milliseconds = int(moment * 1000)
        filters.append(f"[c{index}]adelay={milliseconds}|{milliseconds}[d{index}]")
        delayed.append(f"[d{index}]")
    filters.append(
        f"[voice][bed]{''.join(delayed)}"
        f"amix=inputs={2 + len(delayed)}:duration=first:normalize=0,"
        "loudnorm=I=-15.5:TP=-1.2:LRA=9[a]"
    )

    output = ROOT / "pisama-closed-reliability-loop-v4.mp4"
    ffmpeg(
        "-i",
        str(master),
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
        number(total_duration),
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
        "0",
        "-movflags",
        "+faststart",
        str(output),
    )
    return output


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    GENERATED.mkdir(parents=True, exist_ok=True)
    encode_captures()
    audio_durations = prepare_audio()
    assets = render_design_assets()
    scene_durations = {
        key: value + SCENE_TAIL for key, value in audio_durations.items()
    }

    visuals = {
        "hook": render_hook(scene_durations["hook"]),
        "loop": render_loop_scene("loop", scene_durations["loop"], False),
        "setup-execution": render_setup_execution(
            scene_durations["setup-execution"], assets
        ),
        "evidence": render_stage_scene(
            SCENES[3], "evidence", 2, scene_durations["evidence"], assets
        ),
        "diagnose": render_stage_scene(
            SCENES[4], "diagnose", 3, scene_durations["diagnose"], assets
        ),
        "verify": render_stage_scene(
            SCENES[5], "verify", 4, scene_durations["verify"], assets
        ),
        "prevent": render_stage_scene(
            SCENES[6], "prevent", 5, scene_durations["prevent"], assets
        ),
        "close": render_loop_scene("close", scene_durations["close"], True),
    }

    scene_starts = {}
    current = 0.0
    muxed = []
    for scene in SCENES:
        scene_starts[scene.key] = current
        scene_duration = scene_durations[scene.key]
        muxed.append(mux_scene(scene, visuals[scene.key], scene_duration))
        current += scene_duration

    write_captions(scene_starts, audio_durations)
    master = concat_scenes(muxed)
    output = mix_master(master, current)
    print(
        json.dumps(
            {
                "duration": round(current, 3),
                "output": str(output),
                "scenes": len(SCENES),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# PISAMA Closed Reliability Loop video, v3

The 3:16 master is built around the supplied `pisama-reliability-loop-1200x1200.png`. The image is used as the opening and closing visual, the source for all six chapter cards, the persistent product mini-map, and the color and typography reference.

## Deliverables

- `pisama-closed-reliability-loop-v3.mp4`: final 1080p master with narration, sound design, and switchable English captions
- `poster.jpg`: image-led 16:9 cover frame
- `captions.srt`: English caption sidecar for platforms that replace embedded tracks
- `speaker-notes.md`: timed presentation notes, narration, and proof points
- `storyboard.md`: final edit map
- `quality-review.md`: evidence-based 89/100 score and limitations
- `creative-brief.md`: image-derived design and claim rules
- `narration.txt`: complete approved narration

## Evidence policy

The five synthetic cases are clearly labeled as teaching data and are excluded from the verified 19-case corpus and any production-accuracy claim. The prevention scene was captured from a real local guardrail lifecycle against n8n and PISAMA. It verifies a malformed rejection and valid pass-through, then rolls the workflow back while keeping the audit record.

## Rebuild

Requirements: Python 3.11 or newer, FFmpeg, and CairoSVG. The committed MP3 narration and product captures make the edit reproducible without an ElevenLabs session.

```bash
python artifacts/closed-loop-video/v3/build_v3.py
```

The script regenerates the image-led chapter system, prepares narration, renders the product frames, mixes sound design, and writes the final MP4. Intermediate WAVs, frames, generated graphics, and the draft master are intentionally ignored.

`guardrail_demo_runtime.py` is the evidence-capture helper for the prevention chapter. It requires `PISAMA_API_KEY` in the environment and writes the temporary n8n API key only to the ignored path supplied with `--api-key-file`.

## Master specification

- 1920×1080
- 30 fps
- H.264 High profile, stereo AAC 48 kHz, embedded English captions
- 196.02 seconds
- −16.0 LUFS integrated, −1.49 dB true peak

# PISAMA Closed Reliability Loop v4

This is the evidence-led hero film for the PISAMA and n8n closed reliability loop. It uses real n8n and PISAMA product captures, a verified evaluation corpus, and a real guard lifecycle. The supplied reliability-loop image is the visual map for the whole film.

## Watch

- [Final master](pisama-closed-reliability-loop-v4.mp4)
- [Poster](poster.jpg)
- [Narration](narration.txt)
- [Speaker notes](speaker-notes.md)
- [Quality review](quality-review.md)

Runtime: 2 minutes 31.9 seconds.

## What the film proves

1. A real n8n run creates retained execution evidence.
2. PISAMA isolates a missing input contract and a measured timeout.
3. An operator reviews evidence before changing a control.
4. A new immutable evaluation run scores 18 regression cases while one holdout remains excluded.
5. A deterministic input guard requires a rejection destination before apply.
6. A malformed request is rejected before the consumer, a valid request passes, and rollback remains in the audit record.

The 19-case corpus is provenance-backed. The film does not use synthetic results to support release claims.

## Build

Requirements: Python 3.11 or newer, FFmpeg, FFprobe, and macOS `sips`.

```bash
python3 build_v4.py
python3 verify_v4.py
```

The committed capture assets make the build reproducible without a running n8n or PISAMA instance. Raw capture frames are intentionally ignored. The build preserves the original ElevenLabs narration files, creates paced 48 kHz working audio, renders the product scenes, embeds optional English captions, and writes the final master.

## Delivery properties

- 1920 by 1080 at 30 fps
- H.264 High profile, CRF 17
- Rec.709 primaries, transfer, matrix, and limited range
- AAC stereo at 48 kHz
- Measured at minus 15.3 LUFS with a minus 1.22 dB true peak
- Optional English `mov_text` captions
- 20.45 MB final file

## Boundaries

The film proves one prevention class: an input-schema guard for a data-contract failure. It does not claim that every failure can be automatically repaired. It also avoids customer ROI and traction claims because no verified customer evidence was supplied for this production.

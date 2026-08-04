# PISAMA Closed Reliability Loop v4

This is the evidence-led hero film for the PISAMA and n8n closed reliability loop. It uses real n8n and PISAMA product captures, a verified evaluation corpus, and a real guard lifecycle. The supplied reliability-loop image is the visual map for the whole film.

## Watch

- [Final master](pisama-closed-reliability-loop-v4.mp4)
- [Poster](poster.jpg)
- [Narration](narration.txt)
- [Speaker notes](speaker-notes.md)
- [Quality review](quality-review.md)

Runtime: 3 minutes 18.4 seconds.

## What changed in the calm cut

- A branded introduction establishes the problem before the first dashboard appears.
- The replacement opening narration follows one recorded failure through the promised outcome.
- The reliability-loop image is completely static between fades, removing fractional-pixel shake.
- Stage cards now remain for 2.5 seconds, including a 1.4-second full-opacity hold.
- Dashboard captures play at their recorded speed instead of being accelerated.
- Sequential side notes explain what to notice in the n8n, evidence, diagnosis, verification, and prevention scenes.
- Dashboard narration now continues through the final visible evidence in every scene; the longest voice gap in the complete master is 2.81 seconds.
- Cursor movement follows scene-specific curved, eased paths with deliberate pauses at the relevant controls.
- Restrained gold focus boxes link the Verify and Prevent notes to the exact supporting fields.
- Each complex scene ends with a brief settling beat before the next transition.

## Fix pass (2026-08-04)

An independent multi-perspective review of the released master produced a fix pass:

- Focus rings now appear only while their target is scroll-static in the capture. The verify rings frame the regression and holdout stat tiles exactly; the two rings that previously drifted over scrolling corpus rows were removed in favor of side notes.
- The prevent capture was re-recorded from the live dashboard after the panel copy itself was fixed. The stat every reviewer had misread as a 3 percent success rate now reads "1 of 30 required successful runs" on screen, with an explainer line: 30 is the required count of successful post-repair executions, with zero recurrences, before an operator may conclude prevention. The fifth POST-REPAIR side note echoes the corrected stat.
- The captured guard verification intro is now grammatical: "A guardrail repair can be concluded as prevention only after both checks are observed."
- The rollback note now says plainly that the demo guard was reverted as cleanup and that the audit record remains, resolving the rolled_back badge against the film's promise.
- The holdout side note explains in plain language why one case stays unscored.
- Chapter chips, lower-thirds, and side notes are fully opaque, removing ghosted UI text under the panels.
- The closing card adds a concrete next step: Self-host on GitHub, Pisama-AI/pisama-n8n.

## What the film proves

1. A real n8n run creates retained execution evidence.
2. PISAMA isolates a missing input contract and a measured timeout.
3. An operator reviews evidence before changing a control.
4. A new immutable evaluation run scores 18 regression cases while one holdout remains excluded.
5. A deterministic input guard is proposed for operator review before workflow changes.
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
- Measured at minus 15.62 LUFS with a minus 1.19 dB true peak
- Optional English `mov_text` captions
- 19.74 MB final file

## Boundaries

The film proves one prevention class: an input-schema guard for a data-contract failure. It does not claim that every failure can be automatically repaired. It also avoids customer ROI and traction claims because no verified customer evidence was supplied for this production.

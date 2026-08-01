# V4 quality review

## Final scores

| Perspective | Score | Why |
|---|---:|---|
| Domain expert | 96/100 | The film exposes the failed expression, detector class, measured timeout, immutable run, holdout boundary, human review, guard authorization, two real probes, and rollback record. It keeps diagnosis, verification, and prevention distinct. |
| Technical layman | 92/100 | One missing-field failure anchors the story. Plain-language narration precedes the technical detail, the six-stage image gives viewers a map, and the closing promise is easy to repeat. Some evaluation vocabulary remains necessary. |
| VC or investor | 90/100 | The operational pain, product wedge, buyer, and closed-loop differentiation are visible in a single story. The film does not include traction, customer ROI, or market-size evidence because none was available to verify. |
| Visual and technical craft | 96/100 | Product footage fills the frame, the supplied image controls the art direction, cursor movement adds human pacing, the UI is legible at 1080p, the mix is broadcast-safe, and captions pass strict line and timing checks. |

Overall evidence-supported score: 94/100.

This is the highest honest score for the available proof. Pushing the investor score materially higher would require verified customer outcomes or traction. Pushing the human-demo score higher would require an on-camera presenter or a recorded human voice performance. Neither should be fabricated.

## Improvements made during the final iteration

- Replaced synthetic teaching claims with the verified 19-case corpus and real guard probes.
- Reframed the opening around recurrence risk.
- Made the supplied Closed Reliability Loop image the navigation system and closing frame.
- Increased product footage to full-frame 1920 by 1080 presentation.
- Reduced stage bumpers to 0.9 seconds.
- Added cursor movement and click cues at real interaction moments.
- Added the immutable run identity, sealed holdout, append-only correction, authorization boundary, and rollback proof to the narration.
- Shortened and paced the narration to a 2 minute 31.9 second master.
- Corrected the closing CTA so it no longer obscures the reliability-loop stages.
- Split captions into 44 readable entries with no orphaned fragments.
- Added complete Rec.709 bitstream metadata.

## Verification results

- Full decode: passed
- Duration: 151.855 seconds
- File size: 20.45 MB
- Video: H.264 High, 1920 by 1080, 30 fps, `yuv420p`
- Color: Rec.709 primaries, transfer, matrix, and limited range
- Audio: AAC stereo, 48 kHz
- Loudness: minus 15.3 LUFS integrated
- True peak: minus 1.22 dB
- Captions: 44 entries, two lines maximum, 42 characters per line maximum
- Caption speed: 18.81 characters per second maximum
- Caption display: 1.01 seconds minimum

## Evidence boundaries

The final release claims rely on:

- 19 provenance-backed n8n execution records
- 18 audited regression cases
- one separately sealed and unscored holdout
- a missing `body.required.value` contract failure
- a measured 64.0-second execution against a 30.0-second limit
- a real input guard lifecycle with a required rejection destination
- one malformed request and one valid request
- a retained rollback record

The video proves the input-schema guard class. It does not prove automatic prevention for every detector or failure mode. The voice is a licensed ElevenLabs performance, not an on-camera human presenter.

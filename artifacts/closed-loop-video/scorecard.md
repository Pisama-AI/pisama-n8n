# Video scorecard

Scoring rubric: closed-loop correctness 25, live-action authenticity 20, data honesty 15, visual legibility 15, narration and pacing 15, reproducibility and accessibility 10.

| Category | First cut | Final cut | Assessment |
|---|---:|---:|---|
| Closed-loop correctness | 23 | 23 | Real n8n execution, detection, idempotent retention, human review, immutable regression scoring, holdout exclusion, and revision history are all shown. No unsupported label correction is fabricated. |
| Live-action authenticity | 12 | 16 | Both cuts use continuous captured browser activity. The final adds visible cursor travel and click cues. It is a screencast without a webcam or physical keyboard view. |
| Data honesty | 12 | 15 | The final keeps a persistent synthetic-data label until the release scorecard and explicitly identifies the separate verified corpus. |
| Visual legibility | 9 | 13 | The final adds 1080p section labels, concise captions, and stable holds on result evidence. Dense n8n JSON remains small on phone-sized playback. |
| Narration and pacing | 10 | 11 | Narration follows the actions and finishes within 72 seconds. The macOS system voice is clear but less natural than a human recording. |
| Reproducibility and accessibility | 6 | 9 | The final includes exact narration, speaker notes, an SRT transcript, burned captions, a synthetic manifest, and a reproducible build. Audio is mono. |
| **Total** | **72/100** | **87/100** | The revision clears the required 77-point threshold. |

## Improvements made after the first cut

1. Added continuous cursor motion and gold click cues tied to the actual interaction timestamps.
2. Added persistent synthetic and verified-corpus labels so the accuracy boundary cannot be missed.
3. Added section headers and burned captions for silent viewing and small screens.
4. Normalized narration to a mean level of minus 15.6 dB with a minus 1.5 dB peak.
5. Added a revision-history close showing why append-only labels keep old score runs auditable.

## Verification

- 72.021 seconds
- 1920 by 1080, 30 frames per second, H.264
- 48 kHz mono AAC narration
- Complete decode succeeds with no ffmpeg errors
- Final SHA-256: `1553afbcf8447734e8dd96d73d8d9776de4634d719a841b1969f80c8bb5b3167`

## Remaining limitations

- Local unlicensed n8n Community keeps its native batch Evaluations screen behind instance registration, so the demo uses an actual n8n workflow for execution and Pisama for the full audit dashboard.
- The cursor is rendered over captured real browser activity because tab screenshots do not retain the operating-system pointer.
- The narration is synthesized by the macOS system voice.

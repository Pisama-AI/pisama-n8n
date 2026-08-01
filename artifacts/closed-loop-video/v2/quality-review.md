# Promo v2 quality review

Final score: **89 / 100**. The acceptance target was 77.

| Category | Score | Evidence |
|---|---:|---|
| Story and context | 19 / 20 | The opening explains the hidden-failure problem, maps the five-stage loop, then proves each stage in order. |
| Human-driven product proof | 17 / 20 | Continuous n8n and Pisama interactions show execution, inspection, review, scoring, and revision. Pointer movement and click feedback make the operating sequence legible. |
| Visual craft | 16 / 20 | Custom motion chapters, quiet fades, factual lower-thirds, coherent typography, and a restrained PISAMA palette support the product footage. |
| Narration and sound | 17 / 20 | ElevenLabs narration is split into editable, action-aligned takes. The final mix is 48 kHz AAC at about -16 LUFS with subtle ambience and state-change click cues. |
| Evidence and honesty | 20 / 20 | Synthetic teaching data is disclosed and held outside the verified corpus. The demo distinguishes 19 reviewed cases, 18 regression cases, one excluded holdout, immutable run 3, append-only revisions, and deduplicated reruns. |

## Review passes

1. The first assembly aligned the premium narration with the continuous product captures and extended scenes where the original timing clipped a sentence.
2. The polish pass added chapter fades, cursor feedback, evidence lower-thirds, a quiet sound bed, and loudness normalization.
3. The evidence review found one incorrect lower-third that said one clean and four failed cases. It was corrected to two clean and three failed cases, matching the n8n annotation and narration.

## Verified delivery properties

- Duration: 176.0 seconds.
- Picture: 1920 by 1080, H.264, 30 frames per second.
- Sound: AAC, 48 kHz, integrated loudness about -16.2 LUFS, true peak about -1.34 dBTP.
- Full narration, speaker notes, storyboard, and SRT captions are included beside the video.

## Honest limitations

- The product capture source is 1280 by 720 and is upscaled for the 1080p delivery.
- The pointer path is authored over continuous browser capture. It is purposefully human-paced, but it is not a raw recording of a physical mouse.
- The narrator is a licensed ElevenLabs synthetic voice, not an on-camera human presenter.
- The video uses factual lower-thirds. Full sentence captions are supplied as an SRT sidecar rather than burned into the image.
- The five teaching cases are synthetic by design. The release-gate claim is demonstrated separately on the 19-case reviewed corpus.

The result clears 77 because the complete closed loop is visible and evidence-backed. It does not score in the mid-90s because a true native 4K capture, a recorded human presenter, original music, and a final professional mix would materially improve production value.

# Closed-loop live demo speaker notes

Target duration: 72 seconds. Format: live browser operation with synchronized narration, burned captions, cursor motion, and click cues.

## 00:00 to 00:04, establish scope

On screen: n8n canvas with the `SYNTHETIC DATA ONLY` note and the five-case workflow.

Speaker intent: State that these are teaching cases and are excluded from the 19-case release corpus.

## 00:04 to 00:10, execute in n8n

On screen: The cursor moves to `Execute workflow`; nodes turn green and both branches show five items.

Speaker intent: Explain that detection and idempotent retention run together.

## 00:10 to 00:23, inspect clean and failed cases

On screen: Open `Compare expected and actual`, switch to JSON, then select the timeout case. Two clean cases show empty expected and actual arrays. The timeout shows `F13` in both and `exact_set_match: true`.

Speaker intent: Make clear that a successful evaluation means the detector agrees with an independently declared label, not that every execution was healthy.

## 00:23 to 00:30, prove idempotency

On screen: Open `Show idempotent receipt`. The repeated run shows the stable retained execution IDs and `deduplicated: true` from the ingest response.

Speaker intent: Connect this to duplicate-execution prevention.

## 00:30 to 00:39, triage in Pisama

On screen: The Detections list shows the new node error, missing alert workflow, timeout, and contract findings. Open the timeout.

Speaker intent: Describe the handoff from automated detection to retained evidence.

## 00:39 to 00:49, review evidence

On screen: The timeout detail identifies `SYNTHETIC DEMO: Timeout in inventory sync`, the 64-second duration, Slow Code node, 30-second webhook threshold, 60-second node threshold, and `F13`. Scroll to the review controls and click `Useful finding`.

Speaker intent: Show that a human verdict completes the review step.

## 00:49 to 01:01, run the immutable regression suite

On screen: Open Evaluation. The dashboard still states 19 provenance-backed reviewed cases. Click `Run regression suite`; immutable run 2 completes with 18 regression cases at 100 percent exact-set accuracy and one excluded holdout.

Speaker intent: Keep the synthetic teaching data separate from the release claim and explain the holdout boundary.

## 01:01 to 01:12, audit revisions

On screen: Expand `Review` on the holdout row. Show revision 0, hashes, current labels, and the evidence-required correction form. Do not submit a fabricated correction.

Speaker intent: Explain append-only revisions and why historical score runs remain reproducible.

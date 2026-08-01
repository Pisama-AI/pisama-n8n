# Closed-loop live demo video

The final deliverable is `closed-loop-demo.mp4`, a 72-second, 1080p live-action screencast. It records real interactions in local n8n and Pisama dashboards, including workflow execution, result inspection, evidence review, human feedback, an immutable regression run, and append-only label history.

## Artifacts

- `closed-loop-demo.mp4`: final 1920 by 1080 H.264/AAC video
- `speaker-notes.md`: timed actions and speaker intent
- `narration-*.txt`: exact narration for each live take
- `captions.srt`: portable caption transcript matching the burned captions
- `synthetic-data-manifest.md`: the five teaching cases and expected labels
- `scorecard.md`: first-cut and final scores with limitations
- `prepare_live_demo.py`: creates the isolated synthetic n8n workflow
- `build_video.sh`: reproducibly assembles the recorded frames, narration, cursor, click cues, labels, and captions

## Rebuild

The frame folders are generated capture artifacts and are intentionally kept outside version control. To prepare the synthetic workflow against a running isolated demo:

```bash
PISAMA_VIDEO_N8N_PASSWORD='<generated local demo password>' \
PISAMA_VIDEO_SOURCE_WORKFLOW_ID='<provisioned workflow id>' \
.venv-demo/bin/python artifacts/closed-loop-video/prepare_live_demo.py
```

After recording the three frame sequences at eight frames per second into `frames/n8n-live`, `frames/pisama-live`, and `frames/revision-live`, run:

```bash
artifacts/closed-loop-video/build_video.sh
```

The build uses the macOS system voice for narration, `sips` for transparent overlay assets, and ffmpeg for 30-frame-per-second H.264/AAC output.

## Honesty boundary

The five synthetic cases are for explanation only and are visibly labeled throughout. They never enter the verified 19-case release corpus. The evaluation dashboard scores 18 regression cases and leaves the one protected holdout excluded. The video opens the correction workflow but does not submit a fabricated correction because no truthful new label evidence exists.

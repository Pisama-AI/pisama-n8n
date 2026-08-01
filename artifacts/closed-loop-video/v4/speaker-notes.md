# Speaker notes

Use these notes for a live introduction, investor meeting, or narrated product walkthrough. The final voice track is in [narration.txt](narration.txt).

## 00:00 to 00:14.7, the problem

Purpose: make recurrence, rather than a single red node, the problem.

On screen: a retained data-contract failure, then the verified guard result. The first concrete path is `body.required.value`. The second view shows malformed rejection, valid pass-through, and the rollback record.

Presenter cue: let the viewer read the two yellow evidence labels. Do not add a feature list here.

## 00:14.7 to 00:25.3, the operating model

Purpose: give the audience one map for everything that follows.

On screen: the supplied Closed Reliability Loop image. The six stages are setup, execution, evidence, detect and heal, verify, and prevent.

Presenter cue: stress that diagnosis alone does not close the loop. Verification and recurrence control complete it.

## 00:25.3 to 00:47.0, setup and execution

Purpose: establish that scoring starts from labeled, source-backed records.

On screen: the setup and execution cards, then the n8n evaluation workflow. The browser capture includes the workflow run and its execution notifications. The moving cursor keeps the interaction legible at presentation distance.

Evidence to call out: 19 reviewed records, 18 regression cases, one separately sealed holdout, and stable case identity.

## 00:47.0 to 01:06.9, evidence

Purpose: connect the abstract failure to a specific retained trace.

On screen: PISAMA detection 191. The detector reports `n8n_data_contract`. The record includes the failing node, the expression error, the workflow identity, and the review controls.

Presenter cue: pause on the failed expression. This is the moment the expert audience should be able to audit the claim directly.

## 01:06.9 to 01:26.8, detect and heal

Purpose: show causal diagnosis and the boundary for human judgment.

On screen: PISAMA detection 360. The execution lasted 64.0 seconds against a 30.0-second limit. The review area and suggested control remain visible.

Presenter cue: say clearly that the diagnosis informs a decision. PISAMA does not silently rewrite the workflow.

## 01:26.8 to 01:49.2, verify

Purpose: turn the next build into an immutable release decision.

On screen: a fresh evaluation run, its build revision, the reviewed corpus, exact-match outcomes, and the unscored holdout. The capture scrolls through the corpus while the cursor pauses on case evidence.

Evidence to call out: 18 regression cases, one holdout, 100 percent expected failure-set match, immutable run identity, and append-only label correction history.

## 01:49.2 to 02:11.0, prevent

Purpose: prove recurrence control with two real requests.

On screen: PISAMA detection 3 and its input-schema guard proposal. The repair record shows the malformed request rejected before the consumer, the valid request passed through, and the workflow rolled back with the record retained.

Presenter cue: describe the operator-selected rejection destination. This is an authorization boundary, not decoration.

## 02:11.0 to 02:31.9, close

Purpose: restate the value in buyer language.

On screen: the full reliability loop and a three-line promise in the left margin.

Closing line: “See what failed. Prove the fix. Prevent recurrence.”

Presenter cue: use “teams operating critical n8n workflows” as the buyer definition. Avoid unsupported claims about universal automation or customer ROI.

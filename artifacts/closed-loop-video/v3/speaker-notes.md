# Speaker notes

Runtime: 3:16. Delivery: calm, informed, and concrete. Treat the pointer movement as the presenter thinking in real time. Pause briefly when evidence values appear.

## 00:00 to 00:17.5, the operating model

Open on the supplied reliability-loop image. Let the camera reveal the entire diagram before naming the stages. The key claim is that reliability is an operating cycle, not a single evaluation score.

Narration: “Reliable automation is a loop, not a final score. PISAMA makes six stages visible: design the controls, run the agent, retain the evidence, diagnose and heal, verify with evaluations, then prevent the same failure from returning.”

## 00:17.5 to 00:39, 01 Setup

The Setup card becomes the chapter title, then the n8n editor takes over. Point first to the prominent synthetic-data disclosure. Track the five-case generator and both workflow branches. Do not imply that these teaching cases are part of the verified corpus.

Narration: “Stage one is setup. Before PISAMA sees a result, this n8n workflow declares five synthetic teaching cases, two clean and three failed, with expected failure modes written independently. These cases teach the demo. They never enter the verified release claim.”

Proof on screen: five synthetic teaching cases, two clean, three failed, excluded from the verified 19-case release corpus.

## 00:39 to 01:00.5, 02 Execution

Follow the pointer as the workflow is started. Let the viewer see both branches instead of cutting directly to a result. The left-hand mini-map keeps the stage connected to the original image.

Narration: “Stage two is execution. I start the workflow in n8n. One branch evaluates each trace. The other retains a stable case identity for review. The workflow itself stays visible, so the evaluation is part of the operating system, not a separate spreadsheet.”

Proof on screen: the workflow executes in n8n, evaluation and audit identity are retained in parallel.

## 01:00.5 to 01:27, 03 Evidence

Allow extra time on the returned JSON and the retained execution trace. Call out the empty clean sets before the failures. This prevents the sequence from feeling like a failure-only montage.

Narration: “Stage three is evidence. Clean cases return empty failure-mode sets. The timeout returns F thirteen. The missing-field case returns the contract and expression modes, and the node error is separate. Expected and actual sets match. On a repeat run, every receipt is deduplicated and keeps the original execution identity.”

Proof on screen: expected and actual sets match, and repeat ingestion keeps the original execution identity.

## 01:27 to 01:57, 04 Detect and heal

Move from the source-image card into PISAMA. Scroll at a human reading pace. Hold on the measured timeout, then the contract evidence. End on the review controls. The wording is deliberately conservative: diagnosis precedes human authorization, and no automatic healing is claimed here.

Narration: “Stage four is diagnose and heal. PISAMA separates the failure classes, then keeps the evidence that supports each one. The timeout shows sixty-four seconds against a thirty-second limit, the Slow Code node, and the trace behind F thirteen. The contract finding preserves the missing field and failing expression. Healing begins with an informed human verdict. It does not begin with an automatic mutation.”

Proof on screen: detector class, measured threshold breach, failing node, retained trace, and review controls.

## 01:57 to 02:27, 05 Verify

Shift from a single diagnosis to the release dashboard. Read the corpus split before the score. The order matters because a one-hundred-percent result is meaningful only after the viewer sees the provenance, holdout exclusion, revision, and immutable run record.

Narration: “Stage five is verification. Nineteen provenance-backed cases are reviewed and frozen. Eighteen enter the normal regression run. The protected holdout stays excluded. A new asynchronous run succeeds at one hundred percent exact-set accuracy, with its build revision and per-case results stored immutably. If a label changes, PISAMA appends evidence. Earlier scores do not move.”

Proof on screen: 19 reviewed cases, 18 regression cases, one excluded holdout, immutable run data, append-only label history.

## 02:27 to 02:57, 06 Prevent

This is the highest-risk claim, so stay literal. Show the proposal and the selected rejection destination, then the verification card. The final state says `rolled_back` because the demo restores the original workflow after proving both paths. That retained rollback is part of the audit evidence, not a failed test.

Narration: “Stage six is prevention. For a proven data-contract failure, PISAMA proposes a deterministic input-schema guard. The operator chooses where rejected input goes before apply is allowed. Two real executions verify the result: malformed input is rejected before the consumer, and valid input still passes. That is evidence of recurrence prevention, with rollback retained.”

Proof on screen: input-schema guard proposal, malformed input rejected, valid input passed, rollback record retained.

## 02:57 to 03:16, close the loop

Return to the full reference image. Let the last sentence land before the fade. Do not add a sales claim after it. The visual itself is the final mnemonic.

Narration: “The loop is now closed. A run creates evidence. Evidence creates a reviewed diagnosis. The diagnosis changes a control. Evaluations verify the next build, and a real guard proves the failure stays out. That is the PISAMA closed reliability loop.”

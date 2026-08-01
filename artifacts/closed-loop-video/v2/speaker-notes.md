# Speaker notes

Voice: Sarah, Approachable and Informative, Eleven Multilingual v2. Speed 1.11, stability 0.50, similarity 0.75, style 0.33, speaker boost on.

Delivery: informed product lead, speaking to an engineering peer. Keep the tone conversational. Pause on evidence values. Say “n-eight-n” and “F thirteen” as written.

## 00:00 to 00:11.7, opening truth

On screen: the green execution succeeds while the evidence packet introduces hidden failure modes.

Narration: “An n8n workflow can finish successfully and still fail the user. A slow call, a missing field, or an unhandled node error can disappear into execution history.”

Performance: start calmly. Put weight on “still fail the user.” Leave the final phrase unresolved so the next chapter answers it.

## 00:12.5 to 00:23.4, the loop

On screen: the packet moves through Capture, Detect, Review, Freeze, and Score.

Narration: “Pisama closes that gap. It captures the execution, detects failure evidence, asks for a human verdict, freezes the reviewed label, and scores the next build.”

Performance: keep the five stages rhythmic but natural. Do not turn them into a slogan.

## 00:24.5 to 00:40.9, disclose the teaching data

On screen: the n8n workflow and synthetic-data note are visible. The pointer opens the generator.

Narration: “For this demo, I am using five clearly marked synthetic teaching cases: two clean and three failed. They are never mixed into the release claim. I open the generator so we can see the case identities and their independently declared expected modes.”

Performance: stress “synthetic,” “two clean and three failed,” and “never.” This is a trust-building disclosure.

## 00:41.5 to 00:51.2, run n8n

On screen: the pointer starts the workflow. Both branches complete in the interface.

Narration: “Now I run the workflow in n-eight-n. The upper branch evaluates every trace. The lower branch retains a stable case identity for review.”

Performance: sound like you are operating the tool while speaking. Let the click land just before “run.”

## 00:52.5 to 01:15.9, inspect and rerun

On screen: the pointer opens the comparison output, then the receipt with five deduplicated records.

Narration: “In the result panel, the clean cases have empty failure-mode sets. The timeout is labeled F thirteen. The missing-field case fires the contract and expression modes, and the node error is caught separately. Expected and actual sets match. On this repeat run, Pisama returns the same execution IDs and marks every record deduplicated.”

Performance: slow slightly for detector names. Pause before the deduplication conclusion.

## 01:17.5 to 01:44.2, investigate the timeout

On screen: the handoff reaches Pisama. The pointer opens the timeout, follows the measured duration and trace, then records Useful finding.

Narration: “The workflow hands off to Pisama. The detections list separates node errors, missing alert workflows, timeouts, and data-shape problems. I open the inventory timeout. The finding keeps the measured sixty-four-second duration, both thresholds, the Slow Code node, and the execution trace that supports F thirteen. I can accept the finding, reject it, or mark it fixed. I mark it useful.”

Performance: keep this section diagnostic, not dramatic. Give “sixty-four-second duration” and “both thresholds” enough space to register.

## 01:45.5 to 01:58.6, inspect the contract break

On screen: the pointer opens Data shape mismatch and follows the retained expression evidence.

Narration: “The missing-field case tells a different story. Pisama identifies the data-contract break and the failing expression, so the reviewer sees cause and evidence instead of a generic red execution.”

Performance: contrast this failure with the timeout. Land on “cause and evidence.”

## 02:03.5 to 02:08.7, protect the boundary

On screen: the synthetic packet remains separate from the verified corpus.

Narration: “These five synthetic cases teach the flow. They stay outside the verified corpus.”

Performance: short and definitive. This is a governance point.

## 02:10.5 to 02:34.3, score the next build

On screen: the Evaluation page shows 19 reviewed cases, 18 regression cases, one excluded holdout, and immutable run 3.

Narration: “Evaluation is the release gate. Nineteen provenance-backed cases are reviewed and frozen. A normal run scores eighteen regression cases. The protected holdout remains excluded. I start a new asynchronous run. The run succeeds at one hundred percent exact-set accuracy, with the build revision and per-case results stored as an immutable record.”

Performance: pause after each corpus count. Treat the 100 percent score as a property of this stored run, not a general product claim.

## 02:35.5 to 02:46.4, preserve revision history

On screen: the pointer opens the review form and the append-only revision history.

Narration: “If a label changes, Pisama appends a revision with new evidence. It never rewrites the label history or earlier score runs. That is what makes the loop auditable.”

Performance: emphasize “appends” and “never rewrites.”

## 02:47.5 to 02:55.2, close

On screen: the evidence packet becomes a checked release record.

Narration: “From one failed n-eight-n run to a reviewed, reproducible release signal. That is the Pisama closed loop.”

Performance: finish with confidence, then leave one second of visual hold.

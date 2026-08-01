# Closed-loop n8n evaluation

Pisama has one canonical detector path for ingestion, offline scoring, and n8n's
Evaluation UI. `POST /api/v1/n8n/evaluate` analyzes an execution without retaining it,
creating operational metrics, or broadcasting an event.

## Run the local demo

From the repository root:

```bash
scripts/run_closed_loop_demo.sh
```

The command starts a locally installed n8n on port 5678 when it is not already
running, the Pisama API on port 8400, and the dashboard on port 3555. It retains one
sanitized real n8n Cloud failure in Pisama and generates a four-row n8n Data table CSV
from the committed, independently labeled error corpus. No synthetic execution or
generated label is used.

The terminal prints the exact dashboard, workflow JSON, and CSV paths. On a fresh n8n
installation, complete n8n's owner setup. Then:

1. Import the generated CSV as an n8n Data table.
2. Import `examples/pisama-closed-loop-evaluation.json` as a workflow.
3. Select the imported table in the Evaluation Trigger and Set Outputs nodes.
4. For both HTTP Request nodes, use Header Auth with `Authorization` and the bearer
   value printed by the launcher.
5. When n8n is installed directly on the host, set both Pisama URLs to
   `http://127.0.0.1:8400`. Keep `host.docker.internal` when n8n runs in Docker.
6. Run the n8n evaluation. Its exact-set metric is computed without persistence, while
   the retention branch makes the same real executions available in Pisama.
7. In Pisama Detections, record a verdict, confirm the modes from n8n evidence, and
   freeze the case. Open Evaluation to rerun the suite, inspect mismatches, and download
   the reviewed corpus.

The launcher preserves the Pisama demo database in its printed state directory. It
does not reset the user's n8n account or existing workflows. Press Ctrl-C to stop only
the processes started by the launcher.

## Run from n8n

Import [`examples/pisama-closed-loop-evaluation.json`](../examples/pisama-closed-loop-evaluation.json).
The workflow follows n8n's metric-based evaluation pattern and retains each row for
the review half of the loop:

1. Evaluation Trigger reads one real captured execution per Data table row.
2. One HTTP Request posts that execution to Pisama's pure evaluation endpoint.
3. A second HTTP Request posts it to the persistent webhook endpoint for review.
4. Code compares the complete expected and actual failure-mode sets.
5. Evaluation records the case output and a numeric `exact_set_match` metric.

Create these Data table columns:

| column | value |
|---|---|
| `dataset_id` | Stable dataset release identifier used for idempotent retention |
| `case_id` | Stable reviewed case identifier within that dataset |
| `execution_payload` | Full n8n execution object, or its JSON string |
| `expected_modes` | Reviewed array of expected taxonomy modes, or its JSON string |
| `label_evidence` | The n8n record or workflow fact supporting the label |

Select the same Data table in the trigger and Set Outputs nodes. On both HTTP Request
nodes, select a Header Auth credential with header `Authorization` and value
`Bearer <PISAMA_API_KEY>`. Change the URLs when Pisama is not reachable through
`host.docker.internal:8400`.

The expected modes must be labeled before looking at Pisama's response. A row may have
multiple modes, and an independently confirmed false positive may have an empty array.
The workflow exposes missing and unexpected modes separately so a matching string cannot
hide a multi-label error.

## Review and retain new incidents

On a detection detail page:

1. Record an operator verdict.
2. Verify all suggested modes against the retained n8n execution and workflow settings.
3. Enter the independent evidence and choose `regression` or `holdout`.
4. Freeze the case. One immutable case identity is allowed per retained execution.
5. Open the Evaluation page to run the current detector against every reviewed case,
   inspect split counts and per-case misses, and download the credential-redacted
   manifest.
6. Optionally score that export in a release gate with:

```bash
python eval/closed_loop_eval.py \
  --manifest pisama-evaluation-taxonomy-v1.json \
  --require-exact
```

Use `holdout` only when the case was labeled before the detector change being measured.
The committed `legacy_holdout` preserves earlier evidence but is not presented as a new
future-blind result.

Every frozen label records the exact feedback id, a non-secret fingerprint of the
authenticated credential that reviewed and froze it, and a SHA-256 hash of the retained
payload. The scorer verifies the hash when it is present in an exported manifest.

`GET /api/v1/evaluation-cases/score` performs the same canonical scoring on the server.
It returns aggregate metrics, regression and holdout counts, per-case expected and
actual modes, taxonomy version, and build revision. It never returns retained payloads.
An exact result on reviewed cases is regression evidence for that build. It is not an
estimate of accuracy on unreviewed production traffic.

Labels are never silently edited. Record new operator feedback, then append a correction
with `POST /api/v1/evaluation-cases/{case_id}/revisions`. Inspect the complete review
history with `GET /api/v1/evaluation-cases/{case_id}/revisions`. Exports always use the
latest revision while the earlier labels remain available for audit.

## CI gate

Repository CI requires exact-set parity for all 19 cases, the 18-case regression split,
and the separately disclosed one-case `legacy_holdout`. It also requires every retained
payload to match its recorded SHA-256. Minimum split sizes prevent a deleted or renamed
case from making the gate easier by accident. Undefined precision or recall remains
`null` when a split has no predicted or labeled examples, so an empty class cannot appear
perfect.

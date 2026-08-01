# Closed-loop n8n evaluation

Pisama has one canonical detector path for ingestion, offline scoring, and n8n's
Evaluation UI. `POST /api/v1/n8n/evaluate` analyzes an execution without retaining it,
creating operational metrics, or broadcasting an event.

## Run from n8n

Import [`examples/pisama-closed-loop-evaluation.json`](../examples/pisama-closed-loop-evaluation.json).
The workflow follows n8n's metric-based evaluation pattern:

1. Evaluation Trigger reads one real captured execution per Data table row.
2. HTTP Request posts that execution to Pisama's pure evaluation endpoint.
3. Code compares the complete expected and actual failure-mode sets.
4. Evaluation records the case output and a numeric `exact_set_match` metric.

Create these Data table columns:

| column | value |
|---|---|
| `case_id` | Stable reviewed case identifier |
| `execution_payload` | Full n8n execution object, or its JSON string |
| `expected_modes` | Reviewed array of expected taxonomy modes, or its JSON string |
| `label_evidence` | The n8n record or workflow fact supporting the label |

Select the same Data table in the trigger and Set Outputs nodes. On the HTTP Request
node, select a Header Auth credential with header `Authorization` and value
`Bearer <PISAMA_API_KEY>`. Change the URL when Pisama is not reachable through
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
4. Freeze the case. One immutable case is allowed per retained execution.
5. Export the credential-redacted manifest and score it with:

```bash
python eval/closed_loop_eval.py \
  --manifest pisama-evaluation-taxonomy-v1.json \
  --require-exact
```

Use `holdout` only when the case was labeled before the detector change being measured.
The committed `legacy_holdout` preserves earlier evidence but is not presented as a new
future-blind result.

## CI gate

The repository CI runs `python eval/closed_loop_eval.py --require-exact`. Any missing or
unexpected mode fails the job. Undefined precision or recall remains `null` when a split
has no predicted or labeled examples, so an empty class cannot appear perfect.

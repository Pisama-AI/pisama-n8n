# Closed-loop n8n evaluation

Pisama uses one detector path for live ingestion, pure evaluation, and immutable score
runs. `POST /api/v1/n8n/evaluate` analyzes an execution without retaining it. The
idempotent `POST /api/v1/n8n/evaluation-ingest` endpoint retains a dataset case once,
returns the same execution for an exact retry, and rejects payload drift for that case.

## Run the isolated demo

From the repository root:

```bash
scripts/run_closed_loop_demo.sh
```

The launcher requires Python 3.11, Node 20, `uv`, and `npx`. It creates a new temporary
state directory and then:

1. installs the Python packages and dashboard dependencies when needed;
2. starts pinned n8n 2.32.7 with an isolated user folder and random encryption key;
3. imports all 19 hash-verified real execution records into Pisama;
4. creates the n8n owner, 19-row Data table, configured workflow, and inline auth;
5. starts Pisama in production mode with independent random API and holdout keys;
6. seals the one-case holdout protocol and completes a 19-case immutable audit run;
7. builds and starts the Next.js production server.

The terminal prints the generated n8n password, direct workflow URL, dashboard URL,
audit run ID, and state directory. No existing n8n installation, owner setup, CSV
import, workflow import, URL edit, or credential edit is required. Press Ctrl-C to stop
the processes. Set `PISAMA_DEMO_STATE_DIR` when the temporary database and n8n state
must survive a later run.

n8n's native batch Evaluations UI requires a registered or licensed n8n instance. The
launcher provisions and displays the workflow before registration, while Pisama's entire
capture, review, revision, holdout, scoring, and export loop remains operational. Use
**Register instance** in the n8n Evaluations tab for registered Community access. For
licensed self-hosted n8n, set `PISAMA_DEMO_N8N_LICENSE_KEY` before launching. Never
commit that key. Current availability is documented by
[n8n](https://docs.n8n.io/advanced-ai/evaluations/overview/).

Override ports when defaults are occupied:

```bash
PISAMA_DEMO_N8N_PORT=5701 \
PISAMA_DEMO_N8N_BROKER_PORT=5702 \
PISAMA_DEMO_API_PORT=8501 \
PISAMA_DEMO_DASHBOARD_PORT=3656 \
scripts/run_closed_loop_demo.sh
```

## What the dashboard proves

The Evaluation page shows the full 19-case provenance-backed corpus, not a single
example. Its current release has 18 regression cases and one protected holdout. The
page can:

- queue a non-blocking regression run and poll its persisted status;
- show the latest immutable run ID, build revision, taxonomy, case count, and result;
- compare the expected and actual mode set for every scored case;
- expand every case's append-only label history;
- append an evidence-backed correction without rewriting prior labels;
- download the credential-redacted corpus.

Normal runs exclude holdout cases. A holdout can enter a run only through a sealed
protocol created with the separate holdout authority. The protocol snapshots every
holdout case revision, payload hash, and label hash against a declared baseline build,
then permits one candidate-build release. A candidate cannot equal the baseline.

## Run from n8n

The launcher configures
[`examples/pisama-closed-loop-evaluation.json`](../examples/pisama-closed-loop-evaluation.json)
automatically. For a separately managed eligible n8n instance, import the workflow and
create a Data table with these columns:

| column | value |
|---|---|
| `dataset_id` | Stable dataset release identifier used for idempotent retention |
| `case_id` | Stable reviewed case identifier within that dataset |
| `execution_payload` | Full n8n execution object, or its JSON string |
| `expected_modes` | Independently reviewed taxonomy modes, or their JSON string |
| `label_evidence` | The n8n record or workflow fact supporting the label |

Select the same table in the Evaluation Trigger and Set Outputs nodes. Configure both
HTTP Request nodes with `Authorization: Bearer <PISAMA_API_KEY>`. One request calls the
pure evaluation endpoint. The retention request calls `evaluation-ingest`. The workflow
compares complete expected and actual mode sets, exposes missing and unexpected modes,
and records numeric `exact_set_match` output.

Expected modes must be labeled before looking at Pisama's response. A row can contain
multiple modes. An independently confirmed healthy case has an empty array. Repeating
an n8n run cannot duplicate the retained execution because dataset and case identity is
stable. Reusing that identity with a different payload returns HTTP 409.

## Review and revisions

On the Evaluation page, expand a case with **Review**. The current revision and complete
history are visible together. A correction requires fresh evidence and creates the next
revision. Existing immutable runs keep their original revision, expected labels, payload
hash, and label hash.

The API equivalents are:

- `GET /api/v1/evaluation-cases/{case_id}/revisions`
- `POST /api/v1/evaluation-cases/{case_id}/revisions`
- `POST /api/v1/evaluation-runs`, returns HTTP 202
- `GET /api/v1/evaluation-runs/{run_id}`
- `GET /api/v1/evaluation-runs`

`GET /api/v1/evaluation-cases/score` is a compatibility read. It returns the latest
completed immutable result and never starts synchronous scoring work.

## CI and release gate

The offline gate requires exact-set parity for all 19 cases, including the 18-case
regression split and separately disclosed legacy holdout. Every source payload must
match its committed SHA-256. Minimum split sizes prevent deleted or renamed cases from
making the gate easier. Undefined precision or recall remains `null` when a split has
no predicted or labeled examples.

Score a downloaded corpus with:

```bash
python eval/closed_loop_eval.py \
  --manifest pisama-evaluation-taxonomy-v1.json \
  --require-exact
```

An exact result on reviewed cases is evidence for that build. It is not an accuracy
estimate for unreviewed production traffic.

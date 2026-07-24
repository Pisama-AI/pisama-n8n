# pisama-n8n-engine

Standalone failure detection for n8n workflows.

Pure Python and dependency-free for the six structural detectors. Imports with zero
configuration (no database, no settings, no secrets).

```bash
pip install pisama-n8n-engine
```

```python
from pisama_n8n_engine import analyze

# Structural lane: analyze a workflow definition.
report = analyze(workflow_json=my_workflow)

# Runtime lane: analyze a captured execution's timing, errors, and output.
from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata
turns, meta = execution_to_turns_and_metadata(my_execution)
report = analyze(turns=turns, metadata=meta)

for d in report.fired:
    print(d.detector, d.confidence, d.explanation)
```

Detectors: cycle, runtime data contract, resource, timeout, classified error,
complexity, AI output truncation, retry recovery, missing error workflow,
duplicate-side-effect risk, and evidence-gated AI-agent diagnostics.

For a runtime data-contract finding, use the reusable input-schema guardrail before the
consumer. It returns a supported n8n Code, IF, and clean/reject subgraph, so invalid items
can be routed to an error path while validated items reach the business path unchanged.

```python
from pisama_n8n_engine.guardrails import input_schema_guardrail

guard = input_schema_guardrail(["body.required.value"], position=(220, 0))
```

See the
[input-schema guardrail guide](https://github.com/Pisama-AI/pisama-n8n/blob/main/docs/input-schema-guardrail.md)
for wiring and data-handling details.

The detector core is vendored from the Pisama monorepo (the single source of truth) via
`scripts/extract_from_monorepo.py`; a golden-corpus parity check guards detector behavior.
Standalone trace models and n8n execution parsing stay local so the package has no
undeclared web-service dependencies. This package uses the fair-code
[Pisama Sustainable Use License](https://github.com/Pisama-AI/pisama-n8n/blob/main/LICENSE).

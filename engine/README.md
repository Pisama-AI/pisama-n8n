# pisama-n8n-engine

Failure detection for n8n workflows — the standalone Pisama detection engine.

Pure-Python, dependency-free for the six structural detectors. Imports with zero
configuration (no database, no settings, no secrets).

```python
from pisama_n8n_engine.orchestrator import analyze

# Structural lane — analyze a workflow definition:
report = analyze(workflow_json=my_workflow)

# Runtime lane — analyze a captured execution's real timing/errors/output:
from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata
turns, meta = execution_to_turns_and_metadata(my_execution)
report = analyze(turns=turns, metadata=meta)

for d in report.fired:
    print(d.detector, d.confidence, d.explanation)
```

Detectors: cycle, runtime data contract, resource, timeout, classified error,
complexity, AI output truncation, retry recovery, missing error workflow,
duplicate-side-effect risk, and evidence-gated AI-agent diagnostics.

The detectors are vendored from the Pisama monorepo (the single source of truth) via
`scripts/extract_from_monorepo.py`; a parity check guards against drift. Fair-code
(Sustainable Use License) — see the repository LICENSE.

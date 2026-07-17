# Input-schema guardrail

Use this reusable n8n subgraph at a workflow boundary when a consumer requires
specific JSON fields. It is intentionally separate from a local defensive patch: a patch
can make one consumer safe, while this guard prevents invalid input from reaching every
downstream consumer on its validated branch.

```python
from pisama_n8n_engine.guardrails import input_schema_guardrail

guard = input_schema_guardrail(
    ["body.required.value", "body.customer.id"],
    position=(220, 0),
)
```

Add `guard["nodes"]` and `guard["connections"]` to the workflow, then connect the upstream
source to `guard["entry_node"]`. The fragment has two terminal nodes:

- `guard["rejected_node"]` contains only `_pisama_input_schema.valid` and the missing path
  names. Route it to an error workflow, alert, or explicit rejection response.
- `guard["validated_node"]` contains the original valid item unchanged. Connect it to the
  existing business path.

The paths must match the actual input shape at the boundary. n8n Webhook nodes expose a
JSON request body under `body`, hence `body.required.value` above. The guard treats only
missing and `null` values as invalid. Empty strings and zero are preserved because their
validity is domain-specific. It also omits rejected payload values, so an error route does
not automatically copy sensitive input into a ticket or alert.

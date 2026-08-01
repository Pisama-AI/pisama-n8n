# Synthetic teaching dataset

Dataset ID: `video-synthetic-v1`

This dataset is synthetic and exists only to make the video flows easy to follow. It is excluded from the verified 19-case release corpus and from every production accuracy claim.

| Case | Scenario | Expected modes |
|---|---|---|
| `SYN-01-clean-order-handoff` | Clean order handoff | none |
| `SYN-02-clean-invoice-agent` | Clean invoice agent | none |
| `SYN-03-timeout-inventory-sync` | Timeout in inventory sync | `F13` |
| `SYN-04-missing-customer-field` | Missing required customer field | `n8n_data_contract`, `n8n_expression`, `n8n_missing_error_workflow` |
| `SYN-05-tool-node-error` | Tool node throws an error | `n8n_node_error`, `n8n_missing_error_workflow` |

The generator in `prepare_live_demo.py` derives these teaching records from detector fixtures, replaces their execution and workflow identity, adds `synthetic: true`, and gives every workflow a `SYNTHETIC DEMO` name. Expected labels are declared before Pisama evaluates the records.

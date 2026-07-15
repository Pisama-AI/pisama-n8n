# n8n-nodes-pisama

An n8n community node that forwards workflow executions to [Pisama](https://pisama.ai) for failure detection and self-healing.

Without this node, integrating n8n with Pisama requires wiring an HTTP Request node by hand, computing HMAC signatures yourself, and shaping the payload to match the Pisama webhook contract. With this node, you drop "Pisama" on any workflow, authenticate once, and every subsequent execution is analyzed.

## What Pisama detects in n8n workflows

- Structural: cycles, missing error handlers, schema mismatches between nodes, excessive branching. These read the full workflow JSON, which requires the optional n8n API connection (see below).
- Runtime: token/cost budget overruns, AI node timeouts, unprotected LLM calls, resource exhaustion
- Semantic (when LLM nodes are present): loops, hallucinations, context neglect, coordination breakdown across sub-agents

See [docs.pisama.ai/integrations/n8n](https://docs.pisama.ai/integrations/n8n) for the full detector list.

## Install

In n8n's community nodes settings, enter `n8n-nodes-pisama` and install. Restart n8n. The Pisama node will appear in the node picker.

## Configure

1. Get your API key at [pisama.ai/settings/api-keys](https://pisama.ai/settings/api-keys) (starts with `pisama_`)
2. Register this workflow in Pisama to obtain its webhook secret. Registration is **required**: the Pisama webhook rejects unsigned executions, so you need the secret to send data.
3. In n8n: Credentials → New → Pisama API
4. Paste the API key and the webhook secret. Save.

## Use

Add a Pisama node at the end of any workflow whose executions you want analyzed. Set Operation to "Send Execution". No other config needed.

The node ships real execution status, real start/finish timestamps, per-node run data, and (optionally) the full workflow definition. Analysis runs in the background on Pisama's side, so the node returns immediately.

## Telemetry fidelity: connect the n8n API (recommended)

A community node runs *inside* the execution it is reporting on, so from the node context alone it cannot see the execution's final status, its real duration, the run data of every node, or the full workflow JSON. Without extra configuration the node sends an honest best-effort view: real ids and metadata, a real node-run window, and a status derived from observed upstream errors.

For **authoritative** telemetry, connect your n8n public REST API in the Pisama credential:

1. In n8n: Settings → n8n API → create an API key.
2. In the Pisama credential, set **n8n API URL** (e.g. `https://your-instance.app.n8n.cloud/api/v1`) and **n8n API Key**.

With the API connected, the node fetches the execution record (`GET /executions/{id}?includeData=true`) and forwards the real `status`, `startedAt`/`stoppedAt`, full per-node run data, and the full workflow JSON that the structural detectors and quality assessment depend on. The n8n API key is sent only to your n8n instance, never to Pisama. The `telemetrySource` field on each payload records whether it came from the n8n API (`n8n_api`) or the node context (`execution_context`).

### Toggles

- **Include Full Workflow JSON** — attach the workflow definition for structural quality assessment. The full JSON is only available when the n8n API is connected; without it, only lightweight metadata (id, name, active) is attached and structural checks stay disabled.
- **Run Quality Assessment** — trigger Pisama's structural quality assessment. Requires the full workflow JSON (n8n API connection).

## Security

Payloads are signed with HMAC-SHA256 over `{timestamp}.{body}` using your webhook secret, sent as `X-Pisama-Signature: sha256=…` alongside `X-Pisama-Timestamp` and a per-request `X-Pisama-Nonce` for replay protection.

## Self-hosted Pisama

Set the API URL field in credentials to your own deployment (e.g., `https://pisama.your-company.com/api/v1`). All other behavior is identical.

## License

MIT

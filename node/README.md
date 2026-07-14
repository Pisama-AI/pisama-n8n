# n8n-nodes-pisama

An n8n community node that forwards workflow executions to [Pisama](https://pisama.ai) for failure detection and self-healing.

Without this node, integrating n8n with Pisama requires wiring an HTTP Request node by hand, computing HMAC signatures yourself, and shaping the payload to match the Pisama webhook contract. With this node, you drop "Pisama" on any workflow, authenticate once, and every subsequent execution is analyzed.

## What Pisama detects in n8n workflows

- Structural: cycles, missing error handlers, schema mismatches between nodes, excessive branching
- Runtime: token/cost budget overruns, AI node timeouts, unprotected LLM calls, resource exhaustion
- Semantic (when LLM nodes are present): loops, hallucinations, context neglect, coordination breakdown across sub-agents

See [docs.pisama.ai/integrations/n8n](https://docs.pisama.ai/integrations/n8n) for the full detector list.

## Install

In n8n's community nodes settings, enter `n8n-nodes-pisama` and install. Restart n8n. The Pisama node will appear in the node picker.

## Configure

1. Get your API key at [pisama.ai/settings/api-keys](https://pisama.ai/settings/api-keys) (starts with `pisama_`)
2. In n8n: Credentials → New → Pisama API
3. Paste the key. If you've registered this workflow in Pisama (optional, enables HMAC verification), paste the webhook secret too
4. Save

## Use

Add a Pisama node at the end of any workflow whose executions you want analyzed. Set Operation to "Send Execution". No other config needed.

The node ships per-node outputs, workflow metadata, and (optionally) the workflow definition for structural checks. Analysis runs in the background on Pisama's side — the node returns immediately.

## Self-hosted Pisama

Set the API URL field in credentials to your own deployment (e.g., `https://pisama.your-company.com/api/v1`). All other behavior is identical.

## License

MIT

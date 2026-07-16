import { createHmac, randomBytes } from 'crypto';
import type {
	IDataObject,
	IExecuteFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	JsonObject,
} from 'n8n-workflow';
import { NodeApiError, NodeConnectionTypes } from 'n8n-workflow';

interface PisamaCredentials {
	apiKey: string;
	apiUrl: string;
	webhookSecret?: string;
	n8nApiUrl?: string;
	n8nApiKey?: string;
}

/**
 * Sign a webhook body with the canonical Pisama HMAC scheme.
 *
 * The signed message is `{timestamp}.{body}` — matching the server-side
 * `verify_webhook_signature` (backend/app/core/webhook_security.py) and the
 * reference signers in the Python SDK. The signature header carries a
 * `sha256=` prefix. The nonce is a SEPARATE replay-protection header
 * (`verify_nonce`) and is deliberately NOT part of the signed message.
 */
function signPayload(
	body: string,
	secret: string,
): { signature: string; timestamp: string; nonce: string } {
	const timestamp = Math.floor(Date.now() / 1000).toString();
	const nonce = randomBytes(16).toString('hex');
	const message = `${timestamp}.${body}`;
	const digest = createHmac('sha256', secret).update(message).digest('hex');
	return { signature: `sha256=${digest}`, timestamp, nonce };
}

// n8n terminal execution statuses. `running`/`waiting`/`new` are non-terminal
// and are treated as "not yet authoritative" so the node falls back to its
// best-effort status rather than reporting an in-flight row as final.
const TERMINAL_STATUSES = new Set(['success', 'error', 'crashed', 'canceled', 'failed']);

/**
 * Fetch the authoritative execution record from the n8n public REST API.
 *
 * Kept as a standalone helper (rather than inlined in `execute`) so the
 * credential lookup and the HTTP call live in different function scopes: the
 * n8n API key is a plain credential field sent as `X-N8N-API-KEY` to the user's
 * own n8n instance, so `httpRequestWithAuthentication` (which would attach the
 * Pisama credential instead) is deliberately not used here.
 */
async function fetchN8nExecution(
	ctx: IExecuteFunctions,
	base: string,
	apiKey: string,
	executionId: string,
): Promise<IDataObject> {
	return (await ctx.helpers.httpRequest({
		method: 'GET',
		url: `${base}/executions/${encodeURIComponent(executionId)}`,
		qs: { includeData: true },
		headers: { 'X-N8N-API-KEY': apiKey, Accept: 'application/json' },
		json: true,
	})) as IDataObject;
}

/**
 * POST the signed telemetry payload to the Pisama webhook. Standalone for the
 * same scoping reason as {@link fetchN8nExecution}: the request is authenticated
 * with a manually-built API-key header plus the HMAC signature headers, so the
 * generic `httpRequestWithAuthentication` helper does not apply.
 */
async function postToPisama(
	ctx: IExecuteFunctions,
	url: string,
	headers: Record<string, string>,
	body: string,
): Promise<unknown> {
	const response = await ctx.helpers.httpRequest({
		method: 'POST',
		url,
		headers,
		body,
		json: false,
	});
	return typeof response === 'string' ? JSON.parse(response) : response;
}

/**
 * One node run in the exact shape the backend parser iterates: a `data.main`
 * output matrix plus the run's `source` (the upstream node it came from).
 * `backend/app/ingestion/n8n_parser.py::parse_execution` reads each node's runs
 * as a LIST and pulls `run["data"]["main"][0]`, so a node's output MUST be a
 * single-element list of an object of this shape — never the bare item dict.
 */
interface N8nContextRun {
	source: Array<{ previousNode: string }>;
	data: { main: IDataObject[][] };
}

/**
 * Resolve the name of the node immediately upstream of a given input item.
 *
 * Both `$prevNode.name` and `getInputSourceData().previousNode` derive from the
 * run's source data (`executeData.source.main[0].previousNode`). We prefer the
 * per-item proxy — correct when items fan in from different upstream nodes (e.g.
 * downstream of a Merge) — then fall back to the connection-level input source,
 * then to a stable literal when neither is available (e.g. a manual single-node
 * run with no predecessor). This replaces the old `item.json.__n8n_node_name`
 * lookup, a field n8n never sets at runtime, which collapsed every output to the
 * literal key "unknown".
 */
function resolveUpstreamNodeName(ctx: IExecuteFunctions, itemIndex: number): string {
	try {
		const prev = ctx.getWorkflowDataProxy(itemIndex).$prevNode as { name?: unknown };
		if (prev && typeof prev.name === 'string' && prev.name) return prev.name;
	} catch {
		// The data proxy can be unavailable for this item index; fall through.
	}
	try {
		const src = ctx.getInputSourceData();
		if (src && typeof src.previousNode === 'string' && src.previousNode) return src.previousNode;
	} catch {
		// No input source (e.g. a predecessor-less manual run); fall through.
	}
	return 'unknown';
}

/**
 * Whether an input item carries an upstream error. With "Continue On Fail",
 * n8n attaches the failure either at the item level (`item.error`) or as an
 * `error` field on the item json.
 */
function hasItemError(item: INodeExecutionData): boolean {
	if (item.error) return true;
	const json = item.json as IDataObject | undefined;
	return Boolean(json && json.error !== undefined && json.error !== null);
}

/**
 * Build the best-effort (Tier 2) runData from the items on the node's own input.
 * Groups items by their resolved upstream node name into the list-of-runs shape
 * the backend parser expects, and reports whether any item carried an upstream
 * error. Deliberately at module scope, not inside `execute()`: the reconstructed
 * `{ json }` telemetry objects are payload data — the upstream node's recorded
 * output — not items THIS node returns, so they must not be treated as
 * un-paired node outputs (n8n-nodes-base/missing-paired-item).
 */
function buildContextRunData(
	ctx: IExecuteFunctions,
	items: INodeExecutionData[],
): { runData: Record<string, N8nContextRun[]>; observedError: boolean } {
	const runData: Record<string, N8nContextRun[]> = {};
	let observedError = false;
	for (let i = 0; i < items.length; i++) {
		const item = items[i];
		const nodeName = resolveUpstreamNodeName(ctx, i);
		let runs = runData[nodeName];
		if (!runs) {
			runs = [{ source: [{ previousNode: nodeName }], data: { main: [[]] } }];
			runData[nodeName] = runs;
		}
		runs[0].data.main[0].push({ json: (item.json ?? {}) as IDataObject });
		if (hasItemError(item)) observedError = true;
	}
	return { runData, observedError };
}

export class Pisama implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Pisama',
		name: 'pisama',
		icon: 'file:pisama.svg',
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["operation"]}}',
		description:
			'Forward n8n workflow executions to Pisama for failure detection and self-healing',
		defaults: { name: 'Pisama' },
		usableAsTool: true,
		inputs: [NodeConnectionTypes.Main],
		outputs: [NodeConnectionTypes.Main],
		credentials: [{ name: 'pisamaApi', required: true }],
		properties: [
			{
				displayName: 'Operation',
				name: 'operation',
				type: 'options',
				noDataExpression: true,
				options: [
					{
						name: 'Send Execution',
						value: 'sendExecution',
						description:
							'Forward the current workflow execution to Pisama for analysis',
						action: 'Send execution',
					},
				],
				default: 'sendExecution',
			},
			{
				displayName: 'Include Full Workflow JSON',
				name: 'includeWorkflow',
				type: 'boolean',
				default: true,
				description: 'Whether to attach the workflow definition for structural quality assessment (missing error handlers, cycles, schema mismatches). The FULL workflow JSON is only available when the n8n API is connected in the credential; without it the node can only attach lightweight metadata (ID, name, active) and structural checks stay disabled.',
			},
			{
				displayName: 'Run Quality Assessment',
				name: 'runQuality',
				type: 'boolean',
				default: true,
				description:
					'Whether to trigger Pisama structural quality assessment in the background. Requires the full workflow JSON, which needs the n8n API connection (see the Pisama credential).',
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		// Capture the real moment this node runs. In the best-effort (Tier 2) path
		// it anchors the trace's `startedAt`; the true workflow start is not
		// exposed mid-run, so this is a genuine timestamp honestly labelled via
		// `telemetrySource`, never a stand-in for the workflow's duration.
		const nodeStartedAt = new Date().toISOString();

		const items = this.getInputData();
		const credentials = (await this.getCredentials('pisamaApi')) as unknown as PisamaCredentials;
		const returnData: INodeExecutionData[] = [];

		const includeWorkflow = this.getNodeParameter('includeWorkflow', 0) as boolean;
		const runQuality = this.getNodeParameter('runQuality', 0) as boolean;

		// Execution + workflow metadata from the in-node runtime. getWorkflow()
		// only exposes {id, name, active} — the full JSON is not available here.
		const executionId = this.getExecutionId();
		const workflow = this.getWorkflow();
		const mode = this.getMode();

		// --- Best-effort telemetry from the execution context (Tier 2) ---
		// A mid-run node sees only the items on its own input, so buildContextRunData
		// emits an honest, PARTIAL view: the immediately-upstream node's output in
		// the parser's list-of-runs shape. What n8n does NOT expose to a mid-run
		// node — and which therefore stays absent here, filled in only by the
		// optional n8n-API (Tier 1) path below — is: per-node run timing, the
		// workflow's true start/finish timestamps (`$execution` carries the id and
		// mode but no timing), the run data of non-upstream nodes, and the full
		// workflow JSON (node types + parameters).
		const { runData: contextRunData, observedError } = buildContextRunData(this, items);

		// Status: a mid-run node cannot observe the workflow's FINAL status (the
		// execution is still in flight and n8n exposes no terminal status from the
		// node context), so we derive a best-effort status from observed upstream
		// error markers rather than hardcoding 'success'. The authoritative status
		// arrives only via the n8n API path below.
		let status = observedError ? 'error' : 'success';
		// startedAt: the real moment this node executed, used as the trace's time
		// anchor. It is NOT the workflow's true start (not exposed mid-run); the
		// `telemetrySource: execution_context` field records that provenance.
		let startedAt = nodeStartedAt;
		// finishedAt: the workflow has NOT finished when a mid-run node reports,
		// and n8n exposes no finish time here — so it is honestly null rather than
		// a fabricated `new Date()`. The n8n API path fills it for terminal rows.
		let finishedAt: string | null = null;
		let runData: Record<string, unknown> = contextRunData;
		let workflowJson: IDataObject | undefined;
		let telemetrySource = 'execution_context';

		// --- Authoritative telemetry from the n8n REST API (Tier 1) ---
		// When the credential carries n8n API details, fetch the execution record
		// for authoritative status/timestamps/run data and the full workflow JSON.
		if (credentials.n8nApiUrl && credentials.n8nApiKey) {
			try {
				const base = credentials.n8nApiUrl.replace(/\/$/, '');
				const execution = await fetchN8nExecution(
					this,
					base,
					credentials.n8nApiKey,
					executionId,
				);

				telemetrySource = 'n8n_api';

				const apiStatus = typeof execution.status === 'string' ? execution.status : undefined;
				const apiStarted = typeof execution.startedAt === 'string' ? execution.startedAt : undefined;
				const apiStopped = typeof execution.stoppedAt === 'string' ? execution.stoppedAt : undefined;
				const apiRunData = (((execution.data as IDataObject)?.resultData as IDataObject)
					?.runData as Record<string, unknown>) ?? undefined;
				const apiWorkflow = execution.workflowData as IDataObject | undefined;

				// startedAt is set at execution start and is authoritative even
				// for an in-flight row.
				if (apiStarted) startedAt = apiStarted;
				// stoppedAt / status are only final for a terminal row. For the
				// current (still-running) execution they are null/`running`, so
				// keep the best-effort values in that case.
				if (apiStopped) finishedAt = apiStopped;
				if (apiStatus && TERMINAL_STATUSES.has(apiStatus.toLowerCase())) {
					status = apiStatus;
				}
				if (apiRunData && Object.keys(apiRunData).length > 0) {
					runData = apiRunData;
				}
				if (apiWorkflow && Array.isArray(apiWorkflow.nodes)) {
					workflowJson = apiWorkflow;
				}
			} catch (error) {
				// Non-fatal: fall back to the best-effort context telemetry. The
				// execution is still forwarded so detection is never blocked by a
				// misconfigured or unreachable n8n API.
				this.logger?.warn(
					`Pisama: n8n API fetch failed for execution ${executionId}; sending best-effort telemetry (${(error as Error).message})`,
				);
			}
		}

		const payload: IDataObject = {
			executionId,
			workflowId: workflow.id ?? 'unknown',
			workflowName: workflow.name ?? '',
			mode,
			startedAt,
			finishedAt,
			status,
			telemetrySource,
			data: {
				resultData: {
					runData,
				},
			},
		};

		if (includeWorkflow) {
			// Lightweight, always-honest metadata. Redundant with the top-level
			// ids but harmless, and it distinguishes "workflow known" from
			// "workflow JSON available".
			payload.workflowMeta = {
				id: workflow.id,
				name: workflow.name,
				active: workflow.active,
			};
			// The FULL workflow JSON — only present via the n8n API. It feeds both
			// the structural detectors and the quality assessment, so attach it
			// whenever it's the genuine full definition (never metadata-only,
			// which would drive a degenerate assessment). Whether the quality
			// assessment actually runs is a separate, backend-honored decision.
			if (workflowJson) {
				payload.workflow = workflowJson;
			}
		}

		// Let the backend gate the (heavier) structural quality assessment
		// independently of attaching the workflow JSON for structural detection.
		payload.runQuality = runQuality;

		const body = JSON.stringify(payload);
		const url = `${credentials.apiUrl.replace(/\/$/, '')}/n8n/webhook`;
		const headers: Record<string, string> = {
			'Content-Type': 'application/json',
			'X-Pisama-API-Key': credentials.apiKey,
		};

		if (credentials.webhookSecret) {
			const { signature, timestamp, nonce } = signPayload(body, credentials.webhookSecret);
			headers['X-Pisama-Signature'] = signature;
			headers['X-Pisama-Timestamp'] = timestamp;
			headers['X-Pisama-Nonce'] = nonce;
		}

		try {
			const parsed = await postToPisama(this, url, headers, body);
			returnData.push({ json: parsed as IDataObject, pairedItem: { item: 0 } });
		} catch (error) {
			if (this.continueOnFail()) {
				returnData.push({
					json: { error: (error as Error).message },
					pairedItem: { item: 0 },
				});
			} else {
				throw new NodeApiError(this.getNode(), error as JsonObject);
			}
		}

		return [returnData];
	}
}

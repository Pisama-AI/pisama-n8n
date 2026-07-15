import { createHmac, randomBytes } from 'crypto';
import {
	IDataObject,
	IExecuteFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	JsonObject,
	NodeApiError,
} from 'n8n-workflow';

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
		inputs: ['main'],
		outputs: ['main'],
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
						action: 'Send execution to Pisama',
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
		// Capture a real start timestamp up front so the fallback path reports a
		// genuine (non-fabricated) node-run window instead of two identical
		// `new Date()` values.
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
		// The Pisama node runs mid-execution and only sees its own input items,
		// so this is a partial, honest view: real ids/metadata, real node-run
		// timing, and a status derived from observed upstream error markers
		// rather than a hardcoded 'success'.
		const contextRunData: Record<string, unknown> = {};
		let observedError = false;
		for (const item of items) {
			const json = (item.json ?? {}) as IDataObject;
			const nodeName = json.__n8n_node_name ?? 'unknown';
			contextRunData[String(nodeName)] = json;
			// n8n places an `error` object on items that passed through a failed
			// node with continueOnFail enabled.
			if (json.error !== undefined && json.error !== null) {
				observedError = true;
			}
		}

		let status = observedError ? 'error' : 'success';
		let startedAt = nodeStartedAt;
		let finishedAt = new Date().toISOString();
		let runData: Record<string, unknown> = contextRunData;
		let workflowJson: IDataObject | undefined;
		let telemetrySource = 'execution_context';

		// --- Authoritative telemetry from the n8n REST API (Tier 1) ---
		// When the credential carries n8n API details, fetch the execution record
		// for authoritative status/timestamps/run data and the full workflow JSON.
		if (credentials.n8nApiUrl && credentials.n8nApiKey) {
			try {
				const base = credentials.n8nApiUrl.replace(/\/$/, '');
				const execution = (await this.helpers.httpRequest({
					method: 'GET',
					url: `${base}/executions/${encodeURIComponent(executionId)}`,
					qs: { includeData: true },
					headers: { 'X-N8N-API-KEY': credentials.n8nApiKey, Accept: 'application/json' },
					json: true,
				})) as IDataObject;

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
			const response = await this.helpers.request({
				method: 'POST',
				url,
				headers,
				body,
				json: false,
				resolveWithFullResponse: false,
			});
			const parsed = typeof response === 'string' ? JSON.parse(response) : response;
			returnData.push({ json: parsed });
		} catch (error) {
			throw new NodeApiError(this.getNode(), error as JsonObject);
		}

		return [returnData];
	}
}

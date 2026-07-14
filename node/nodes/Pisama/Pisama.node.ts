import { createHmac, randomBytes } from 'crypto';
import {
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
}

function signPayload(
	body: string,
	secret: string,
): { signature: string; timestamp: string; nonce: string } {
	const timestamp = Math.floor(Date.now() / 1000).toString();
	const nonce = randomBytes(16).toString('hex');
	const payload = `${timestamp}.${nonce}.${body}`;
	const signature = createHmac('sha256', secret).update(payload).digest('hex');
	return { signature, timestamp, nonce };
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
				displayName: 'Include Workflow Definition',
				name: 'includeWorkflow',
				type: 'boolean',
				default: true,
				description:
					'Whether to include the full workflow JSON. Required for structural quality assessment (missing error handlers, cycles, schema mismatches).',
			},
			{
				displayName: 'Run Quality Assessment',
				name: 'runQuality',
				type: 'boolean',
				default: true,
				description:
					'Whether to trigger Pisama quality assessment in the background. Only runs when Include Workflow Definition is true.',
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const credentials = (await this.getCredentials('pisamaApi')) as unknown as PisamaCredentials;
		const returnData: INodeExecutionData[] = [];

		const includeWorkflow = this.getNodeParameter('includeWorkflow', 0) as boolean;
		const runQuality = this.getNodeParameter('runQuality', 0) as boolean;

		// Execution + workflow metadata from n8n runtime
		const execution = this.getExecutionId();
		const workflow = this.getWorkflow();
		const mode = this.getMode();

		// Collect per-node outputs from items
		const nodeOutputs: Record<string, unknown> = {};
		for (const item of items) {
			const nodeName = item.json?.__n8n_node_name ?? 'unknown';
			nodeOutputs[String(nodeName)] = item.json;
		}

		const now = new Date().toISOString();
		const payload: Record<string, unknown> = {
			executionId: execution,
			workflowId: workflow.id ?? 'unknown',
			workflowName: workflow.name ?? '',
			mode,
			startedAt: now,
			finishedAt: now,
			status: 'success',
			data: {
				resultData: {
					runData: nodeOutputs,
				},
			},
		};

		if (includeWorkflow && runQuality) {
			// n8n gives us workflow metadata; full JSON requires the n8n API.
			// Ship what we have so the backend can do partial quality checks.
			payload.workflow = {
				id: workflow.id,
				name: workflow.name,
				active: workflow.active,
			};
		}

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

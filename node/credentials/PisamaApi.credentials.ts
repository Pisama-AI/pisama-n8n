import {
	IAuthenticateGeneric,
	ICredentialTestRequest,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

export class PisamaApi implements ICredentialType {
	name = 'pisamaApi';
	displayName = 'Pisama API';
	documentationUrl = 'https://docs.pisama.ai/integrations/n8n';
	properties: INodeProperties[] = [
		{
			displayName: 'API Key',
			name: 'apiKey',
			type: 'string',
			typeOptions: { password: true },
			default: '',
			required: true,
			description:
				'Your Pisama API key. Create one at pisama.ai/settings/api-keys. Starts with pisama_.',
		},
		{
			displayName: 'API URL',
			name: 'apiUrl',
			type: 'string',
			default: 'https://api.pisama.ai/api/v1',
			description:
				'Pisama API base URL. Change only for self-hosted deployments.',
		},
		{
			displayName: 'Webhook Secret',
			name: 'webhookSecret',
			type: 'string',
			typeOptions: { password: true },
			default: '',
			description:
				'HMAC secret for signing webhook payloads. Shown once when you register the workflow in Pisama. Registration is required: the Pisama webhook rejects unsigned executions.',
		},
		{
			displayName: 'n8n API URL',
			name: 'n8nApiUrl',
			type: 'string',
			default: '',
			placeholder: 'https://your-instance.app.n8n.cloud/api/v1',
			description:
				'Optional. Base URL of your n8n public REST API. When set (with an API key), the node fetches authoritative execution status, real start/finish timestamps, per-node run data, and the full workflow JSON — the only source that unblinds the structural quality checks. Leave empty to send best-effort telemetry from the node execution context.',
		},
		{
			displayName: 'n8n API Key',
			name: 'n8nApiKey',
			type: 'string',
			typeOptions: { password: true },
			default: '',
			description:
				'Optional. n8n public API key (Settings → n8n API). Sent as X-N8N-API-KEY only to the n8n API URL above, never to Pisama. Enables authoritative, full-fidelity execution telemetry.',
		},
	];

	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: {
			headers: {
				'X-Pisama-API-Key': '={{$credentials.apiKey}}',
			},
		},
	};

	test: ICredentialTestRequest = {
		request: {
			baseURL: '={{$credentials.apiUrl}}',
			url: '/health',
			method: 'GET',
		},
	};
}

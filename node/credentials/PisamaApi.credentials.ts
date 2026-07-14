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
				'Optional HMAC secret for signing webhook payloads. Shown once when you register a workflow.',
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

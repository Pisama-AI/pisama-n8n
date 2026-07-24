# Contributing

Contributions that improve detector accuracy, telemetry fidelity, security,
self-hosting, or n8n compatibility are welcome.

## Validation

```bash
python -m pip install -e "engine[test]" -e "server[test,mcp]"
python -m pytest -q engine/tests server/tests
python benchmarks/parity_check.py
cd dashboard
npm ci
npx tsc --noEmit
npm run build
npm run test:e2e
```

Tests must use sanitized repository fixtures. Never commit credentials,
production payloads, customer workflows, or customer data.

Open a pull request with the problem statement, compatibility impact, license
impact, and commands used for validation.

# Security Policy

## Required runtime configuration

The app is designed to fail closed unless these values are configured:

- `WITNESS_PREP_API_KEYS`
- `CORS_ORIGINS`

Do not use wildcard CORS in production.

## Upload handling

The backend accepts uploaded text/markdown case files and returns opaque file IDs. Raw server file paths must not be accepted from clients.

Current limits:

- max upload size: 10 MB;
- allowed extensions: `.txt`, `.md`;
- uploaded files are stored under the application data directory using generated names.

## Sensitive legal material

Uploaded files may contain privileged or confidential legal material. Operators should:

- restrict access to the backend API;
- use HTTPS behind any reverse proxy;
- define a retention policy for uploaded files and transcripts;
- delete uploads after the session when possible;
- avoid exposing transcript or scorecard endpoints to public networks.

## Credential handling

- Do not commit `.env` or `.env.*` files.
- Rotate any key that appears in commits, logs, screenshots, or release artifacts.
- Keep LiveKit, model-provider, and application API keys separate.

## If exposure occurs

1. Revoke or rotate affected credentials.
2. Remove exposed files from the active branch.
3. Review logs and generated artifacts.
4. Rebuild deployments from a clean commit.
# CrossExam

An experimental, voice-enabled cross-examination training platform for witnesses and legal advocates.

CrossExam combines a FastAPI backend, LiveKit-based real-time communication, structured case ingestion, adversarial questioning, session controls, and post-session scoring. The repository is an active prototype, not a production legal service.

## Current capabilities

- Upload plain-text or Markdown case materials.
- Create and manage isolated practice sessions.
- Stream witness answers and examiner questions over WebSockets.
- Generate LiveKit participant tokens for real-time rooms.
- Pause, resume, inspect, and destroy sessions.
- Produce interim and final scorecard data.
- Restrict API access with configured application keys.
- Enforce explicit CORS origins, upload limits, and path-safe file handling.

## Repository structure

```text
backend/
  config.py              Environment-based application settings
  llm_agent/             Case ingestion and examiner logic
  orchestrator/          FastAPI app, sessions, and LiveKit gateway
  scorecard/             Performance analysis and scoring
  vad_engine/            Voice and turn-completion logic
config/                  LiveKit server configuration
docker/                  Local LiveKit Docker Compose setup
frontend/                Browser client and static assets
scripts/                 Local helper scripts
tests/                   Automated tests
```

## Requirements

- Python 3.11 or newer
- Docker Desktop or Docker Engine with Compose
- A LiveKit API key and secret
- An OpenRouter API key when using hosted model inference

## Local setup

### 1. Clone and enter the repository

```bash
git clone https://github.com/jswizzle3737/crossexam.git
cd crossexam
```

### 2. Create a Python environment

**PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Linux, macOS, or WSL**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure local secrets

Copy the example file and replace every placeholder:

```bash
cp .env.example .env
```

PowerShell equivalent:

```powershell
Copy-Item .env.example .env
```

Required values:

```env
LIVEKIT_API_KEY=replace-with-a-generated-key
LIVEKIT_API_SECRET=replace-with-a-long-random-secret
WITNESS_PREP_API_KEYS=replace-with-a-separate-long-random-value
CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
OPENROUTER_API_KEY=replace-when-using-openrouter
```

Do not reuse the LiveKit secret as the application API key.

### 4. Start LiveKit locally

```bash
docker compose --env-file .env -f docker/docker-compose.yml up -d
```

The Compose configuration exposes LiveKit only on the local machine by default. Review the networking and authentication configuration before any remote deployment.

### 5. Start the application

```bash
uvicorn backend.orchestrator.main:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000`.

## Authentication

Protected HTTP endpoints require one of the values configured in `WITNESS_PREP_API_KEYS`:

```http
Authorization: Bearer YOUR_APPLICATION_API_KEY
```

Browser WebSocket clients pass the application API key through the documented `token` query parameter. Do not place production credentials in public URLs, logs, screenshots, or client-side source code.

## Tests

```bash
pytest -q
```

Some LiveKit integration tests require the local LiveKit container to be running.

## Security notes

- Never commit `.env`, provider keys, session data, uploaded evidence, or production LiveKit configuration.
- Treat uploaded case material as confidential.
- The included in-memory rate limiter is suitable for local development, not a distributed production deployment.
- Use HTTPS/WSS, durable authentication, external rate limiting, encrypted storage, and a formal retention policy before handling real client or witness material.
- Rotate any credential that has been committed or shared outside its intended environment.

## Project status

The detailed build plan is preserved in [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md). Some planned components remain experimental or incomplete. Verify actual code and test coverage before relying on a roadmap item.

## Legal use

This software is a training and development prototype. It does not provide legal advice, determine witness credibility, or replace professional judgment.

## License

Licensed under the [Apache License 2.0](LICENSE).

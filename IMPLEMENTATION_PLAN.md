# CrossExam Technical Roadmap

Last reviewed: 2026-07-13

## Repository role

This repository is the retained FastAPI/LiveKit technical experiment for real-time cross-examination training. The primary product and user-experience work now belongs in `jswizzle3737/Crossed`.

Use this repository to evaluate infrastructure that may later be migrated selectively:

- LiveKit room and participant handling;
- FastAPI session orchestration;
- WebSocket event streaming;
- voice-activity and turn-completion logic;
- pause, resume, inspection, and destruction of sessions; and
- scorecard-oriented backend separation.

Do not develop duplicate product features in both repositories.

## Current architecture

```text
Browser client
  ├─ HTTP API for setup, uploads, controls, and scorecards
  ├─ WebSocket stream for examination events
  └─ LiveKit room for real-time media

FastAPI application
  ├─ authentication and configuration
  ├─ case-material ingestion
  ├─ session lifecycle and orchestration
  ├─ examiner/model gateway
  ├─ VAD and turn-completion logic
  └─ interim and final scorecards
```

## Security baseline

All examples and deployments must follow these rules:

1. Credentials come from environment variables or a secret manager.
2. Never place example secrets, shared development keys, or provider tokens in tracked files.
3. Bind local services to loopback unless remote access is intentionally configured.
4. Use explicit CORS origins.
5. Use HTTPS and WSS for remote environments.
6. Treat uploaded evidence and session transcripts as confidential.
7. Keep application API keys separate from LiveKit credentials.
8. Do not place production credentials in WebSocket URLs, screenshots, logs, or client bundles.
9. Delete temporary uploads and expired session data according to `docs/DATA_RETENTION.md`.
10. Rotate any credential that was committed or distributed outside its intended environment.

## Configuration pattern

Use placeholders only:

```env
LIVEKIT_URL=http://127.0.0.1:7880
LIVEKIT_API_KEY=replace-with-generated-key
LIVEKIT_API_SECRET=replace-with-long-random-secret
WITNESS_PREP_API_KEYS=replace-with-separate-application-key
OPENROUTER_API_KEY=replace-when-required
CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
```

LiveKit receives its key map at runtime through `LIVEKIT_KEYS`; tracked YAML must not contain reusable credentials.

## Development sequence

### 1. Reproducible local environment

- Maintain bounded dependency ranges in `requirements.txt`.
- Record the Python version used in CI.
- Keep Docker image tags reviewed and intentional.
- Add a generated lock or constraints file before any production deployment.
- Verify the application fails closed when required credentials are missing.

### 2. Session isolation

- Assign an unguessable session identifier.
- Ensure uploads, transcripts, room names, and scorecards remain scoped to one session.
- Reject attempts to access another session’s files or events.
- Destroy in-memory and temporary session state on explicit deletion and expiry.

### 3. Real-time transport

- Confirm LiveKit rooms are created with short, intentional lifetimes.
- Generate narrowly scoped participant tokens.
- Test reconnect, disconnect, duplicate participant, and expired-token behaviour.
- Keep microphone interruption and barge-in logic independent from model selection.

### 4. Examiner model gateway

- Define a provider-neutral request interface.
- Log provider, model, latency, and failure category without logging confidential prompt content.
- Add timeouts, cancellation, bounded retries, and useful user-facing failures.
- Prefer inexpensive models for non-critical classification tasks.
- Never silently fall back to a different provider when confidential material is involved.

### 5. Scoring and debrief

Score observable training behaviours rather than truthfulness or credibility. Candidate dimensions include:

- responsiveness;
- unnecessary volunteering;
- consistency with supplied material;
- ability to ask for clarification;
- maintenance of composure;
- recognition of compound or unclear questions; and
- recovery after interruption.

Every score should link to specific transcript events and explain the basis for the result.

### 6. Testing

Required test groups:

- authentication and authorization;
- upload size, type, and path handling;
- session isolation and expiry;
- LiveKit token scope and room lifecycle;
- WebSocket authentication and disconnects;
- model timeout and provider failure paths;
- transcript and scorecard consistency; and
- retention and deletion behaviour.

Run the standard suite with:

```bash
pytest -q
```

LiveKit integration tests may require the local container.

## Promotion criteria

A component should be considered for migration into `Crossed` only when:

- it solves a current product requirement;
- it materially improves latency, reliability, or maintainability;
- its deployment burden is justified;
- its authentication and data-handling paths are tested; and
- it can be integrated without creating two competing implementations.

## Explicitly deferred

- public multi-tenant deployment;
- storage of real client or witness material;
- automated credibility judgments;
- autonomous legal advice;
- biometric identification or emotion inference; and
- expensive media generation unrelated to training quality.

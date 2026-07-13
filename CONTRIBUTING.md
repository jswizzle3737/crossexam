# Contributing

## Repository scope

`crossexam` is the retained FastAPI/LiveKit infrastructure experiment. The canonical user-facing cross-examination product is `jswizzle3737/Crossed`.

Submit work here only when it concerns:

- LiveKit and WebRTC infrastructure;
- FastAPI session orchestration;
- WebSocket event transport;
- voice activity and turn completion;
- session lifecycle controls; or
- scorecard backend design.

Do not duplicate UI, provider-selection, navigation, case-setup, or general product features already being developed in `Crossed`.

## Development process

1. Create a focused branch from the current default branch.
2. Keep one logical change per pull request.
3. Add or update tests for behaviour changes.
4. Run `pytest -q` before requesting review.
5. Do not commit `.env`, credentials, evidence, transcripts, generated scorecards, or local session data.
6. Document new environment variables in `.env.example`.
7. Explain any new external service, port, stored data class, and deletion behaviour.

## Pull request checklist

- [ ] The change belongs in this infrastructure experiment rather than `Crossed`.
- [ ] Tests cover the success and failure paths.
- [ ] Authentication and session isolation were considered.
- [ ] No reusable secrets or personal data are included.
- [ ] Logs omit credentials and confidential content.
- [ ] Documentation and `.env.example` are current.
- [ ] Retention and deletion behaviour is defined.
- [ ] The migration value to `Crossed` is stated when relevant.

## Design rules

- Prefer explicit failure over silent provider fallback.
- Keep provider-specific code behind a small interface.
- Keep microphone/VAD logic independent from model choice.
- Use environment-based configuration.
- Bind development services to loopback by default.
- Treat all uploaded case material as confidential.
- Do not score credibility, honesty, or psychological state.

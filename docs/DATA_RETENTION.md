# Data Retention and Deletion

This repository is a development prototype. Do not use real client, witness, privileged, or court-file material without a separately reviewed production data policy and deployment.

## Data classes

| Data | Default handling |
|---|---|
| Uploaded case material | Temporary, session-scoped, deleted when the session is destroyed or expires |
| Extracted text and case digest | Temporary, session-scoped, deleted with the source upload |
| Live audio | Streamed; not recorded by default |
| Transcript events | In memory by default; deleted with the session |
| Scorecards | Temporary unless the user explicitly exports them |
| Provider request metadata | May include model, latency, and failure category; must not include confidential prompt text |
| Authentication and application logs | Minimize content and rotate logs; never log credentials or complete evidence |

## Development defaults

- Sessions should expire after a bounded period of inactivity.
- Explicit session destruction should remove uploads, extracted text, transcript state, generated scorecards, and room access.
- Temporary files must use session-specific directories with path-safe identifiers.
- Failed uploads and interrupted processing must clean up partial files.
- Browser storage must not silently preserve evidence or transcripts.
- Audio recording is disabled unless a separate feature explicitly enables it with clear notice and consent.

## Production requirements

Before handling real material, define and test:

1. the legal and operational purpose for every retained data class;
2. the retention period and deletion trigger;
3. where data is stored and backed up;
4. who can access it;
5. encryption in transit and at rest;
6. provider retention and model-training settings;
7. user export and deletion controls;
8. incident response and breach notification procedures; and
9. deletion from backups and derived artifacts.

## Verification tests

Automated tests should confirm that:

- one session cannot read another session’s files or transcript;
- expired sessions are removed;
- explicit deletion removes primary and derived files;
- failed processing does not leave partial uploads;
- logs omit tokens and confidential prompt bodies; and
- exported material is created only after an explicit user action.

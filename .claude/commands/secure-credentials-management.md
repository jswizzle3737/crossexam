---
name: secure-credentials-management
description: Workflow command scaffold for secure-credentials-management in crossexam.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /secure-credentials-management

Use this workflow when working on **secure-credentials-management** in `crossexam`.

## Goal

Removes hardcoded credentials from the codebase and moves them to environment variables or local configuration, updating related files to ensure secure handling.

## Common Files

- `config/*.yaml`
- `scripts/*.sh`
- `.env.example`
- `.gitignore`
- `docker/docker-compose.yml`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Remove sensitive credentials from committed configuration files.
- Update scripts or configuration to load credentials from environment variables.
- Update environment template files to document required variables.
- Update .gitignore to exclude local runtime or credential files.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.
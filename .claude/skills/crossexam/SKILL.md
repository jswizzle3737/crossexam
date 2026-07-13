```markdown
# crossexam Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill provides guidance on contributing to the `crossexam` TypeScript codebase. It covers coding conventions, secure credentials management workflow, testing patterns, and common development commands. The repository emphasizes security, clarity, and maintainability, with a focus on handling sensitive information responsibly.

## Coding Conventions

**File Naming**
- Use camelCase for file names.
  - Example: `userService.ts`, `configLoader.ts`

**Import Style**
- Use relative imports for modules within the project.
  ```typescript
  import { getUser } from './userService';
  ```

**Export Style**
- Prefer named exports.
  ```typescript
  // userService.ts
  export function getUser(id: string) { /* ... */ }
  export function createUser(data: UserData) { /* ... */ }
  ```

**Commit Patterns**
- Commit messages may use prefixes such as `security`, `docs`, `chore`.
- Keep commit messages concise (average ~50 characters).
  - Example: `security: move API keys to env variables`

## Workflows

### Secure Credentials Management
**Trigger:** When sensitive credentials (e.g., API keys) need to be secured or have been exposed in the codebase.  
**Command:** `/secure-credentials`

1. **Remove sensitive credentials** from any committed configuration files.
   - Example: Remove hardcoded keys from `config/default.yaml`.
2. **Update scripts or configuration** to load credentials from environment variables.
   - Example:
     ```typescript
     // Before:
     const apiKey = 'HARDCODED_KEY';

     // After:
     const apiKey = process.env.API_KEY;
     ```
3. **Update environment template files** (e.g., `.env.example`) to document all required variables.
   - Example:
     ```
     # .env.example
     API_KEY=your-api-key-here
     ```
4. **Update `.gitignore`** to exclude local runtime or credential files.
   - Example:
     ```
     # .gitignore
     .env
     config/local.yaml
     ```
5. **(Optional)** Update `docker-compose.yml` or similar files to reference environment variables.
   - Example:
     ```yaml
     environment:
       - API_KEY=${API_KEY}
     ```

**Files Involved:**
- `config/*.yaml`
- `scripts/*.sh`
- `.env.example`
- `.gitignore`
- `docker/docker-compose.yml`

## Testing Patterns

- Test files follow the pattern: `*.test.*` (e.g., `userService.test.ts`)
- Testing framework is not explicitly specified; check test files for framework usage.
- Place tests alongside the modules they test or in a dedicated `tests/` directory.

**Example Test File:**
```typescript
// userService.test.ts
import { getUser } from './userService';

describe('getUser', () => {
  it('returns user for valid id', () => {
    // test implementation
  });
});
```

## Commands

| Command              | Purpose                                                      |
|----------------------|--------------------------------------------------------------|
| /secure-credentials  | Initiate the secure credentials management workflow          |
```

```markdown
# crossexam Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches you the core development patterns and conventions used in the `crossexam` TypeScript codebase. You'll learn about file organization, import/export styles, testing patterns, and how to follow the project's workflows. This guide is ideal for contributors aiming for consistency and maintainability in their code.

## Coding Conventions

### File Naming
- Use **snake_case** for all file names.

  **Example:**
  ```
  user_service.ts
  exam_utils.ts
  ```

### Import Style
- Use **relative imports** for modules within the project.

  **Example:**
  ```typescript
  import { calculateScore } from './score_utils';
  ```

### Export Style
- Use **named exports** rather than default exports.

  **Example:**
  ```typescript
  // In user_service.ts
  export function getUser(id: string) { ... }

  // In another file
  import { getUser } from './user_service';
  ```

### Commit Patterns
- Commit messages are freeform, sometimes with prefixes, and average around 50 characters.
- Strive for clarity and conciseness in commit messages.

  **Example:**
  ```
  Add validation to exam submission form
  ```

## Workflows

### Adding a New Feature
**Trigger:** When implementing a new functionality.
**Command:** `/add-feature`

1. Create a new file using snake_case.
2. Write your feature using TypeScript, following import/export conventions.
3. Add or update relevant tests in a corresponding `*.test.*` file.
4. Commit your changes with a clear, concise message.
5. Open a pull request for review.

### Fixing a Bug
**Trigger:** When resolving a reported bug.
**Command:** `/fix-bug`

1. Locate the bug in the codebase.
2. Apply the fix, ensuring you follow coding conventions.
3. Update or add tests to cover the bug scenario.
4. Commit with a message describing the fix.
5. Submit a pull request.

### Writing and Running Tests
**Trigger:** When verifying code correctness.
**Command:** `/run-tests`

1. Write tests in files matching the `*.test.*` pattern.
2. Use the project's preferred (unknown) testing framework.
3. Run tests using the project's test runner (see project documentation or scripts).
4. Ensure all tests pass before committing.

## Testing Patterns

- Test files follow the `*.test.*` naming convention (e.g., `user_service.test.ts`).
- The specific testing framework is not detected; check project documentation for details.
- Place tests alongside or near the modules they test.

  **Example:**
  ```
  user_service.ts
  user_service.test.ts
  ```

- Tests should cover both typical and edge cases for each function or module.

## Commands

| Command      | Purpose                                 |
|--------------|-----------------------------------------|
| /add-feature | Start the workflow for adding features  |
| /fix-bug     | Begin the bugfix workflow               |
| /run-tests   | Run the test suite                      |
```

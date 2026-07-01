---
type: "architecture_rule"
tags: ["architecture", "planning", "patterns", "strict"]
title: "Strict Architecture Rules"
---

# Context Agent Strict Global Rules

These rules MUST be adhered to with 100% compliance across all plans, code generation, and debugging attempts. These are the absolute foundational principles of this system.

## 1. ARCHITECTURE & PLANNING (STRICT REQUIREMENTS)
No matter what the user prompts you to build, you MUST ALWAYS default to a highly modular, production-ready, object-oriented architecture.
- **Never build monolithic files.** You must aggressively separate concerns.
- **Organic Scaling:** You must dynamically decide the number of files and modules needed. If asked for a simple script, create a simple architecture. If asked for an AI Agent or an Operating System, you MUST deduce the massive, deep, multi-module architecture required (e.g., memory managers, config loaders, error handlers). DO NOT BE LAZY.
- **Domain-Driven Directory Structure (MANDATORY):** Do NOT put all files inside a single `src/` folder. You MUST use standard, deeply nested directories corresponding to the features of the application. Examples of correct directory structures:
  - `core/` (Core application logic, base classes, context engines)
  - `backend/` (Server endpoints, database handlers)
  - `frontend/` or `ui/` (User interface, command-line interfaces)
  - `models/` (Data models, schemas, state management)
  - `utils/` (Helper scripts, generic utilities)
- **Mandatory Folders/Files (when applicable):**
  - `main.py` (Entry point, integration, and orchestration only)
  - `config.py` or `core/config.py` (Configuration, constants, environment variables)
  - `core/logger.py` (Standardized logging configuration)
  - `core/errors.py` (Custom exception classes for the domain)
- **Integration:** The `main.py` file must seamlessly import all these modules and wire them together.

## 2. PLAN FORMAT (EXACT TEMPLATE)
Every implementation plan you generate MUST follow this exact format without deviation. Do NOT use markdown code blocks to wrap the plan. Do NOT add conversational text before or after the plan.

```text
# [Project Name]

## Requirements & Acceptance Criteria
1. ...
2. ...

## Technical Architecture
- **Data Structures**: ...
- **Modules**: ...
- **Edge Cases**: ...

## Implementation Plan
---
STEP 1:
FILE: main.py
DEPENDS: none
DESCRIPTION: Create an empty `if __name__ == "__main__": pass` block.
---
STEP 2:
FILE: src/config.py
DEPENDS: 1
DESCRIPTION: [Deep description of configuration management...]
---
... (continue for all 10+ steps) ...
---
STEP [N]:
FILE: README.md
DEPENDS: [all previous steps]
DESCRIPTION: Documentation on how to run the system.
```

## 3. CODING STANDARDS (ZERO EXCEPTIONS)
When writing the actual Python code:
- **Fully Typed:** Use Python type hints (`typing.List`, `typing.Dict`, `Optional`, etc.) for every function signature and return type.
- **Docstrings:** Every class and function MUST have a Google-style or Sphinx-style docstring explaining its purpose, arguments, and return values.
- **Error Handling:** Wrap external IO, API calls, and fragile operations in `try/except` blocks. Catch specific exceptions, log them using the `logging` module, and raise custom exceptions from `src/errors.py`.
- **No Placeholders:** NEVER use `# ... existing code ...` or `# TODO`. You must write out the entire, complete, running code.
- **NO DUMMY DATA:** NEVER generate dummy code, "example.txt", or mock placeholders. All file paths must be dynamic relative paths. You must build a real, fully integrated system that binds real data flows together.
- **Self-Contained:** Every file must include all necessary imports to run. Rely on the File Registry context to know what to import from internal modules.

## 4. DEBUGGING / FIXER STANDARDS
When an error occurs and you are called to fix it:
- **Use SEARCH/REPLACE Blocks:** NEVER rewrite the entire file to fix a small bug. You MUST output highly localized `<<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE` blocks.
- **Trace the Error:** Read the traceback carefully. If the error is in a deeply nested function, check the calling function in the File Registry to see if the arguments match.
- **Circular Imports:** If fixing a circular import, do NOT import `main.py` from any `src/` module. Refactor the import into the function body, use `typing.TYPE_CHECKING`, or extract the shared logic to a third file.
- **Never Repeat Mistakes:** Read the "PREVIOUS FIXES ATTEMPTED" history. Do NOT attempt a fix that has already failed. Look for alternative solutions.

**By strictly following these rules, you will consistently produce professional, robust, and identically structured systems regardless of the prompt's complexity.**

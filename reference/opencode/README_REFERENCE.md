# OpenCode reference copy

Read-only copy of the agent core of OpenCode (https://github.com/sst/opencode),
MIT licensed (see LICENSE), taken at commit a0fdbf9b91ed2cf8bfd778ccec340285403eddc2.

Only `packages/core/src` is copied — the agent loop, tools, prompts and
compaction. It is TypeScript and is NOT imported or executed by Context Agent;
it is kept as a design reference for the Python agent loop in `core/agent/`.

Most useful files:
- packages/core/src/plugin/system-prompt/meta.txt   system prompt used for Llama models
- packages/core/src/tool/plugin/edit.ts              exact-match edit tool + miss hints
- packages/core/src/tool/plugin/read.ts              paged file reads (2000-line cap)
- packages/core/src/tool-output.ts                   tool output caps (2000 lines / 50 KB)
- packages/core/src/session/compaction.ts            context compaction + summary template
- packages/core/src/session/runner/                  the step loop, max-steps prompt
- packages/core/src/plugin/plan.ts                   read-only plan mode

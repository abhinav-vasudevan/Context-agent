"""
Context Agent's agent-loop engine.

    workspace.py    fit-or-retrieve snapshot, repo map from AST
    actions.py      text action protocol (FILE / EDIT / READ / SEARCH / BRAIN / RUN / DONE)
    diagnostics.py  automatic checks (syntax, ruff, pyright, smoke run)
    prompts.py      system / plan prompts (adapted from OpenCode)
    loop.py         AgentLoop: plan() and run()
"""

from core.agent.loop import AgentCallbacks, AgentLoop, AgentResult, parse_plan_files

__all__ = ["AgentLoop", "AgentCallbacks", "AgentResult", "parse_plan_files"]

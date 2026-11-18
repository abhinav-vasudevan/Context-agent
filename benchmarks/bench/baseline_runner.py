"""
Single-shot baseline — the same model asked to write the whole project in one
call. Uses the agent's own LLMClient (same model tag, temperature and 16k
context window), so the only difference from the agent is the pipeline.

    python -m bench.baseline_runner --task bank_system --out <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import time
from pathlib import Path

from bench import settings
from bench.agent_runner import prepare_agent_env

SYSTEM_PROMPT = """You are an expert Python developer. Write a complete, working, multi-file Python project that satisfies the user's specification exactly.

Output EVERY file of the project, each in exactly this format:

### FILE: <relative/path.py>
```python
<full file contents>
```

Rules:
- Output complete files only — no placeholders, no "..." and no TODOs.
- Follow every name, signature and behaviour in the specification exactly.
- Use only the Python standard library unless the specification says otherwise.
"""

_FILE_BLOCK = re.compile(
    r"#+\s*FILE:\s*`?([^\s`]+)`?\s*\n+```[\w+-]*\s*\n(.*?)\n```", re.DOTALL)


def parse_files(raw: str) -> dict[str, str]:
    files = {}
    for path, body in _FILE_BLOCK.findall(raw):
        path = path.strip().lstrip("./").replace("\\", "/")
        if path and ".." not in Path(path).parts and not Path(path).is_absolute():
            files[path] = body.rstrip() + "\n"
    return files


async def run(task_id: str, out_dir: Path) -> dict:
    prepare_agent_env()
    from bench.meter import install as install_meter
    meter = install_meter(out_dir / "llm_calls.jsonl")
    meter.set_context(task=task_id, variant="baseline")
    from core.llm_client import LLMClient

    task = json.loads((settings.TASKS_DIR / task_id / "task.json").read_text(encoding="utf-8"))
    workspace = out_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    llm = LLMClient()
    t0 = time.time()
    result = {"task": task_id, "variant": "baseline", "model": settings.BENCH_MODEL}
    try:
        raw = await llm.generate(prompt=task["prompt"], system=SYSTEM_PROMPT)
        (out_dir / "raw_output.md").write_text(raw, encoding="utf-8")
        files = parse_files(raw)
        for path, body in files.items():
            dest = workspace / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body, encoding="utf-8")
        result.update(phase="done", files_written=sorted(files), execute_success=bool(files))
    except Exception as e:
        result.update(phase="crashed", error=str(e))
    result["seconds"] = round(time.time() - t0, 1)
    result["llm_calls"] = len(meter.records)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[logging.FileHandler(out_dir / "baseline.log", encoding="utf-8")],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    result = asyncio.run(run(args.task, out_dir))
    (out_dir / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result.get(k) for k in ("task", "variant", "phase", "files_written", "seconds")}))


if __name__ == "__main__":
    main()

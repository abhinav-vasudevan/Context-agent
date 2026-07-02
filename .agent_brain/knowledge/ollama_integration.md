---
type: "integration_rule"
tags: ["ollama", "llm", "api"]
title: "Ollama Integration Protocol"
---

# Ollama Integration

How to integrate with local Ollama models STRICTLY using `qwen3.6:27b` via HTTP using the `requests` library. Do NOT use hallucinated pip packages like `ollama`.

## Endpoints
- **Generate:** `http://127.0.0.1:11434/api/generate`
- **Chat:** `http://127.0.0.1:11434/api/chat`

## Example Usage: Generate
```python
import requests

response = requests.post('http://127.0.0.1:11434/api/generate', json={
    'model': 'qwen3.6:27b',
    'prompt': 'Why is the sky blue?',
    'stream': False
})
print(response.json()['response'])
```

## Example Usage: Chat
```python
import requests

response = requests.post('http://127.0.0.1:11434/api/chat', json={
    'model': 'qwen3.6:27b',
    'messages': [{'role': 'user', 'content': 'Hello'}],
    'stream': False
})
print(response.json()['message']['content'])
```

## Streaming
To stream, set `'stream': True` and iterate over `response.iter_lines()`. Use `json.loads(line)` on each line to extract the `response` or `message` token.

## Model Pulling Requirement
IMPORTANT: You MUST STRICTLY use the model name `qwen3.6:27b` and NOTHING ELSE. No placeholders. You must include code in `main.py` to pull the model BEFORE running inference using `subprocess.run(['ollama', 'pull', 'qwen3.6:27b'])`.

"""
LLM Client — async wrapper for Ollama's REST API.

Handles:
  - Streaming token generation (for live UI display)
  - Non-streaming generation (for simpler calls)
  - Retry logic with exponential backoff
  - Token counting (word-based approximation)
  - Health check for Ollama connectivity
  - Transparent logging of every request/response
"""

from __future__ import annotations
import httpx
import json
import logging
import asyncio
import time
from typing import AsyncIterator, Optional, Callable
import os

import config

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

log = logging.getLogger(__name__)


class LLMClient:
    """Async wrapper for the Ollama /api/generate endpoint or Google Gemini API."""

    def __init__(
        self,
        base_url: str = config.OLLAMA_BASE_URL,
        model: str = config.OLLAMA_MODEL,
        num_ctx: int = config.OLLAMA_NUM_CTX,
        temperature: float = config.OLLAMA_TEMPERATURE,
        timeout: int = config.OLLAMA_REQUEST_TIMEOUT,
    ):
        # Always set temperature — used by both Gemini and Ollama paths
        self.temperature = temperature

        self.use_groq = getattr(config, "USE_GROQ", False) and getattr(config, "GROQ_API_KEY", "")
        self.use_gemini = getattr(config, "USE_GEMINI", False) and getattr(config, "GEMINI_API_KEY", "")
        
        if self.use_groq:
            self.groq_api_key = config.GROQ_API_KEY
            self.model = getattr(config, "GROQ_MODEL", "llama-3.3-70b-versatile")
            self.base_url = "https://api.groq.com/openai/v1/chat/completions"
            # Use generous timeouts
            self.timeout = httpx.Timeout(timeout=float(timeout), connect=30.0, read=float(timeout), write=30.0, pool=30.0)
            log.info(f"Initialized Groq API with model {self.model}.")
        elif self.use_gemini:
            if not HAS_GEMINI:
                log.warning("google-generativeai is not installed. Run 'pip install google-generativeai'. Falling back to Ollama.")
                self.use_gemini = False
            else:
                genai.configure(api_key=config.GEMINI_API_KEY)
                self.gemini_model = genai.GenerativeModel(
                    model_name="gemini-2.0-flash", # Best generic coding model
                    system_instruction=None # Set dynamically
                )
                self.model = "gemini-2.0-flash"
                log.info("Initialized Google Gemini API.")
        
        if not self.use_groq and not self.use_gemini:
            self.base_url = base_url.rstrip("/")
            self.model = model
            self.num_ctx = num_ctx
            # Use proper httpx.Timeout with generous connect/read timeouts
            self.timeout = httpx.Timeout(
                timeout=float(timeout),
                connect=30.0,
                read=float(timeout),
                write=30.0,
                pool=30.0,
            )

        # Track usage
        self.total_calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self._logged_delta = False

    # ── Token counting (word-based approximation) ─────────────────────

    @staticmethod
    def count_tokens(text: str) -> int:
        """
        Approximate token count using word-based heuristic.
        Roughly 1 token ≈ 0.75 words for English text / code.
        This avoids needing tiktoken for Ollama models.
        """
        if not text:
            return 0
        # Split by whitespace and punctuation-like boundaries
        words = text.split()
        # Code has more tokens per word due to symbols
        return int(len(words) * 1.3)

    @staticmethod
    def truncate_to_tokens(text: str, max_tokens: int) -> str:
        """Truncate text to approximately max_tokens."""
        words = text.split()
        # Reverse the token approximation: tokens / 1.3 ≈ words
        max_words = int(max_tokens / 1.3)
        if len(words) <= max_words:
            return text
        truncated = " ".join(words[:max_words])
        return truncated + "\n... [truncated]"

    # ── Non-streaming generation ──────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        system: str = "",
    ) -> str:
        """
        Generate a completion. Returns the full response text.
        Internally uses streaming to collect the full response.
        """
        chunks = []
        async for chunk in self.generate_stream(prompt=prompt, system=system):
            chunks.append(chunk)
        return "".join(chunks)

    # ── Streaming generation ──────────────────────────────────────────

    async def generate_stream(
        self,
        prompt: str,
        system: str = "",
        on_token: Optional[Callable[[str], None]] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
        stop: Optional[list[str]] = None,
    ) -> AsyncIterator[str]:
        """
        Stream tokens from Ollama as they arrive.
        Yields individual text chunks (content only, not thinking).
        Includes retry logic with exponential backoff.

        Args:
            prompt: The user/task prompt
            system: System prompt (instructions)
            on_token: Optional sync callback for each content token (for UI updates)
            on_thinking: Optional sync callback for each thinking token (for UI updates)
            stop: Optional list of stop sequences
        """
        last_error = None
        current_max_tokens = 8192
        attempt = 0
        while True:
            try:
                async for token in self._do_stream(prompt, system, on_token, on_thinking, stop, max_tokens_override=current_max_tokens):
                    yield token
                return  # Success — exit retry loop
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
                last_error = e
                if attempt < config.OLLAMA_MAX_RETRIES - 1:
                    wait = config.OLLAMA_RETRY_BACKOFF * (2 ** attempt)
                    log.warning(
                        "LLM request failed (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1, config.OLLAMA_MAX_RETRIES, repr(e), wait,
                    )
                    await asyncio.sleep(wait)
                    attempt += 1
                else:
                    log.error("LLM network request failed after %d attempts: %s", config.OLLAMA_MAX_RETRIES, repr(e))
                    raise
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 413:
                    if current_max_tokens is not None and current_max_tokens > 2048:
                        current_max_tokens = current_max_tokens // 2
                        log.warning("HTTP 413 Payload Too Large. Reducing max_tokens to %d and retrying...", current_max_tokens)
                        continue
                    elif current_max_tokens is not None:
                        current_max_tokens = None
                        log.warning("HTTP 413 Payload Too Large. Stripping max_tokens entirely and retrying...")
                        continue
                    else:
                        # Last resort: truncate the prompt itself to ~50%
                        prompt_tokens = self.count_tokens(prompt)
                        if prompt_tokens > 2000:
                            new_size = prompt_tokens // 2
                            prompt = self.truncate_to_tokens(prompt, new_size)
                            current_max_tokens = 4096  # Reset max_tokens to something small
                            log.warning(
                                "HTTP 413 Payload Too Large even without max_tokens. Truncating prompt from %d to %d tokens and retrying...",
                                prompt_tokens, new_size
                            )
                            continue
                        log.error("HTTP 413 Payload Too Large and prompt is already small (%d tokens). Cannot recover.", prompt_tokens)
                        raise
                elif e.response.status_code == 429 or e.response.status_code >= 500:
                    last_error = e
                    # For 429s, allow up to 10 attempts since rate limits (e.g. Tokens per Minute) can take 60s to clear.
                    max_attempts = 10 if e.response.status_code == 429 else config.OLLAMA_MAX_RETRIES
                    
                    if attempt < max_attempts - 1:
                        wait = config.OLLAMA_RETRY_BACKOFF * (2 ** attempt)
                        if e.response.status_code == 429:
                            retry_after = e.response.headers.get("Retry-After")
                            if retry_after and retry_after.replace('.','',1).isdigit():
                                wait = float(retry_after) + 1.0
                            else:
                                wait = max(wait, 20.0) # Wait at least 20s if no header is provided
                        log.warning(
                            "LLM API rate limit or server error (HTTP %d). Attempt %d/%d. Retrying in %.1fs...",
                            e.response.status_code, attempt + 1, max_attempts, wait
                        )
                        await asyncio.sleep(wait)
                        attempt += 1
                    else:
                        log.error("LLM HTTP error failed after %d attempts: %s", max_attempts, repr(e))
                        raise
                else:
                    # Non-retryable HTTP error (e.g. 400 Bad Request, 404 Not Found)
                    raise
            except ValueError as e:
                # If the stream itself returned a JSON error indicating Payload Too Large
                if "Too Large" in str(e):
                    if current_max_tokens is not None and current_max_tokens > 2048:
                        current_max_tokens = current_max_tokens // 2
                        log.warning("Stream API Error: Payload Too Large. Reducing max_tokens to %d and retrying...", current_max_tokens)
                        continue
                    elif current_max_tokens is not None:
                        current_max_tokens = None
                        log.warning("Stream API Error: Payload Too Large. Stripping max_tokens entirely and retrying...")
                        continue
                    else:
                        # Last resort: truncate the prompt itself
                        prompt_tokens = self.count_tokens(prompt)
                        if prompt_tokens > 2000:
                            new_size = prompt_tokens // 2
                            prompt = self.truncate_to_tokens(prompt, new_size)
                            current_max_tokens = 4096
                            log.warning(
                                "Stream API Error: Payload Too Large. Truncating prompt from %d to %d tokens and retrying...",
                                prompt_tokens, new_size
                            )
                            continue
                        log.error("Stream API Error: Payload Too Large and prompt is already small. Cannot recover.")
                        raise
                raise
            except Exception:
                # Other non-retryable errors
                raise

    async def _do_stream(
        self,
        prompt: str,
        system: str,
        on_token: Optional[Callable[[str], None]],
        on_thinking: Optional[Callable[[str], None]] = None,
        stop: Optional[list[str]] = None,
        max_tokens_override: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Internal streaming implementation (single attempt)."""
        if self.use_groq:
            log.info(
                "LLM request (Groq): model=%s, prompt_len=%d, system_len=%d",
                self.model, len(prompt), len(system),
            )
            start_time = time.monotonic()
            
            headers = {
                "Authorization": f"Bearer {self.groq_api_key}",
                "Content-Type": "application/json"
            }
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                "temperature": self.temperature,
            }
            if max_tokens_override is not None:
                payload["max_tokens"] = max_tokens_override
            if stop:
                payload["stop"] = stop
                
            prompt_tokens = self.count_tokens(prompt + system)
            completion_tokens = 0
            
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    async with client.stream(
                        "POST",
                        self.base_url,
                        headers=headers,
                        json=payload,
                    ) as resp:
                        try:
                            resp.raise_for_status()
                        except httpx.HTTPStatusError as e:
                            await e.response.aread()
                            raise
                            
                        # If the API returns a JSON error instead of an event stream, it will have a different content type
                        content_type = resp.headers.get("content-type", "")
                        if "application/json" in content_type:
                            body = await resp.aread()
                            log.error("API returned JSON instead of stream: %s", body.decode("utf-8", errors="replace"))
                            raise ValueError(f"API Provider Error: {body.decode('utf-8', errors='replace')}")

                        async for line in resp.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    
                                    # Some APIs return stream errors as JSON chunks like {"error": {"message": "..."}}
                                    if "error" in data:
                                        err_msg = data["error"]
                                        if isinstance(err_msg, dict):
                                            err_msg = err_msg.get("message", str(err_msg))
                                        raise ValueError(f"API Provider Stream Error: {err_msg}")
                                        
                                    choices = data.get("choices", [])
                                    if choices:
                                        finish_reason = choices[0].get("finish_reason")
                                        if finish_reason == "length":
                                            log.warning("LLM output truncated by token limit (finish_reason='length'). Partial output will be used.")
                                            break
                                            
                                        delta = choices[0].get("delta", {})
                                        token = delta.get("content", "")
                                        
                                        # Handle reasoning tokens from advanced models (DeepSeek, Qwen reasoning, etc)
                                        reasoning = delta.get("reasoning", "") or delta.get("reasoning_content", "") or delta.get("thought", "")
                                        if reasoning:
                                            if on_thinking:
                                                on_thinking(reasoning)
                                            if not token:
                                                # Don't yield reasoning as content
                                                continue
                                        
                                        if not token and delta and "role" not in delta and "tool_calls" not in delta:
                                            if not self._logged_delta:
                                                log.warning("Unknown delta format from model %s: %s", self.model, delta)
                                                self._logged_delta = True

                                        if token:
                                            completion_tokens += self.count_tokens(token)
                                            if on_token:
                                                on_token(token)
                                            yield token
                                except json.JSONDecodeError:
                                    continue
                
                self.total_calls += 1
                self.total_prompt_tokens += prompt_tokens
                self.total_completion_tokens += completion_tokens
                elapsed = time.monotonic() - start_time
                log.info(
                    "LLM response: %d prompt + %d completion tokens (est), %.1fs",
                    prompt_tokens, completion_tokens, elapsed,
                )
            except Exception as e:
                log.error("Groq streaming failed: %s", repr(e))
                raise
            return

        if self.use_gemini:
            # Recreate model with new system instructions if changed
            self.gemini_model = genai.GenerativeModel(
                model_name="gemini-2.0-flash",
                system_instruction=system if system else None
            )
            log.info(
                "LLM request (Gemini): model=%s, prompt_len=%d, system_len=%d",
                self.model, len(prompt), len(system),
            )
            start_time = time.monotonic()
            
            prompt_tokens = 0
            try:
                prompt_tokens = self.count_tokens(prompt + system)
            except Exception:
                pass

            try:
                generation_config_dict = {"temperature": self.temperature}
                if stop:
                    generation_config_dict["stop_sequences"] = stop
                
                response = await self.gemini_model.generate_content_async(
                    prompt,
                    stream=True,
                    generation_config=genai.types.GenerationConfig(**generation_config_dict)
                )
                
                completion_tokens = 0
                async for chunk in response:
                    token = chunk.text
                    if token:
                        completion_tokens += self.count_tokens(token)
                        if on_token:
                            on_token(token)
                        yield token
                
                self.total_calls += 1
                self.total_prompt_tokens += prompt_tokens
                self.total_completion_tokens += completion_tokens
                elapsed = time.monotonic() - start_time
                log.info(
                    "LLM response: %d prompt + %d completion tokens (est), %.1fs",
                    prompt_tokens, completion_tokens, elapsed,
                )
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                    err_msg = (
                        "Gemini API quota exhausted. Your free-tier daily limit has been reached. "
                        "Options: 1) Wait for the quota to reset, 2) Switch to Ollama by setting USE_GEMINI=False in config.py, "
                        "3) Enable billing on your Google AI Studio account."
                    )
                else:
                    err_msg = f"Gemini API error: {err_str}"
                log.error("Gemini streaming failed: %s", err_msg)
                raise RuntimeError(err_msg) from e
            return

        # ── Ollama implementation — uses /api/chat with think:true ──
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        options = {
            "num_ctx": self.num_ctx,
            "temperature": self.temperature,
        }
        if stop:
            options["stop"] = stop

        # Bypass broken CUDA if configured
        if hasattr(config, "OLLAMA_NUM_GPU"):
            options["num_gpu"] = config.OLLAMA_NUM_GPU

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "think": True,
            "options": options,
        }

        log.info(
            "LLM request (Ollama): model=%s, prompt_len=%d, system_len=%d",
            self.model, len(prompt), len(system),
        )

        start_time = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload,
                ) as resp:
                    try:
                        resp.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        await e.response.aread()
                        raise
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            msg = data.get("message", {})
                            
                            # Handle thinking tokens (separate field from content)
                            thinking_token = msg.get("thinking", "")
                            if thinking_token:
                                if on_thinking:
                                    on_thinking(thinking_token)
                                # Don't yield thinking as content
                            
                            # Handle content tokens
                            content_token = msg.get("content", "")
                            if content_token:
                                if on_token:
                                    on_token(content_token)
                                yield content_token
                            
                            if data.get("done", False):
                                self.total_calls += 1
                                prompt_tokens = data.get("prompt_eval_count", 0)
                                completion_tokens = data.get("eval_count", 0)
                                self.total_prompt_tokens += prompt_tokens
                                self.total_completion_tokens += completion_tokens
                                elapsed = time.monotonic() - start_time
                                log.info(
                                    "LLM response: %d prompt + %d completion tokens, %.1fs",
                                    prompt_tokens, completion_tokens, elapsed,
                                )
                                return
                        except json.JSONDecodeError:
                            continue

        except httpx.HTTPStatusError as e:
            err_msg = f"Ollama Error ({e.response.status_code}). "
            if e.response.status_code == 500:
                err_msg += (
                    "This usually means your computer ran out of RAM. "
                    "Try restarting Ollama or freeing up memory."
                )
            elif e.response.status_code == 404:
                err_msg += (
                    f"Model '{self.model}' not found. "
                    f"Please run 'ollama run {self.model}' in a terminal to download it."
                )
            else:
                err_msg += f"Details: {e.response.text}"
            log.error("LLM streaming failed: %s", err_msg)
            raise RuntimeError(err_msg) from e

        except httpx.ConnectError:
            err_msg = (
                f"Cannot connect to Ollama at {self.base_url}. "
                "Make sure Ollama is running (run 'ollama serve' in a terminal)."
            )
            log.error(err_msg)
            raise RuntimeError(err_msg)

    # ── Health check ──────────────────────────────────────────────────

    async def health_check(self) -> dict:
        """
        Check if Ollama/Gemini is reachable and the configured model is available.
        Returns a dict with status info for display in the UI.
        """
        if getattr(self, 'use_groq', False):
            return {
                "ollama_running": True, 
                "model_available": True,
                "model_name": self.model,
                "llm_provider": "groq",
                "available_models": getattr(config, "GROQ_MODELS", []),
                "error": None,
            }

        if getattr(self, 'use_gemini', False):
            return {
                "ollama_running": True, # UI expects this key to be true if backend LLM is up
                "model_available": True,
                "model_name": self.model,
                "llm_provider": "gemini",
                "error": None,
            }

        result = {
            "ollama_running": False,
            "model_available": False,
            "model_name": self.model,
            "llm_provider": "ollama",
            "error": None,
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                result["ollama_running"] = True

                models = resp.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                # Check if our model (or a variant like "llama3.2:3b") is available
                base_name = self.model.split(":")[0]
                result["model_available"] = any(
                    base_name in name for name in model_names
                )
                if not result["model_available"]:
                    result["error"] = (
                        f"Model '{self.model}' not found. "
                        f"Available: {', '.join(model_names[:5])}. "
                        f"Run: ollama pull {self.model}"
                    )
        except httpx.ConnectError:
            result["error"] = (
                f"Cannot connect to Ollama at {self.base_url}. "
                "Start it with: ollama serve"
            )
        except Exception as e:
            result["error"] = f"Health check failed: {e}"

        return result

    def get_usage(self) -> dict:
        """Return cumulative usage statistics."""
        return {
            "total_calls": self.total_calls,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
        }

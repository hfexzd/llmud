from abc import ABC, abstractmethod
import json
import os
import httpx


class LLMClient(ABC):
    """Provider-agnostic LLM client interface."""

    @abstractmethod
    async def generate(self, system_prompt: str, user_message: str) -> str:
        """Send a prompt and return the raw text response."""
        ...

    async def generate_stream(self, system_prompt: str, user_message: str):
        """Yield the response text in chunks as it arrives.

        Default implementation is non-streaming: it awaits generate() and
        yields the full text once. Providers that support real token streaming
        (DeepSeekClient) override this to yield incremental deltas.
        """
        yield await self.generate(system_prompt, user_message)


class DeepSeekClient(LLMClient):
    """DeepSeek API implementation."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        timeout: float = 60.0,
    ):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.model = os.environ.get("DEEPSEEK_MODEL", model)
        self.base_url = os.environ.get("DEEPSEEK_BASE_URL", base_url)
        self.timeout = timeout

    async def generate(self, system_prompt: str, user_message: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"DeepSeek API error {response.status_code}: {response.text}"
                )
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def generate_stream(self, system_prompt: str, user_message: str):
        """Yield response deltas as they arrive (real token streaming).

        Uses the OpenAI-compatible streaming SSE format: each line is
        `data: {json}` with choices[0].delta.content, terminated by
        `data: [DONE]`.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/chat/completions",
                headers=headers, json=payload,
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise RuntimeError(
                        f"DeepSeek API error {response.status_code}: {body.decode(errors='replace')}"
                    )
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {}).get("content")
                    if delta:
                        yield delta


class MockLLMClient(LLMClient):
    """Mock client for testing — returns a preset response."""

    def __init__(self, response: str = ""):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        return self.response

    async def generate_stream(self, system_prompt: str, user_message: str):
        """Yield the preset response in a few chunks to exercise the
        streaming/accumulation path in tests (real providers stream tokens)."""
        self.calls.append((system_prompt, user_message))
        text = self.response or ""
        if not text:
            return
        # Split into ~4 roughly-equal chunks so the incremental extractor and
        # the frontend both see multi-chunk assembly.
        step = max(1, len(text) // 4)
        for i in range(0, len(text), step):
            yield text[i:i + step]
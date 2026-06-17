from abc import ABC, abstractmethod
import os
import httpx


class LLMClient(ABC):
    """Provider-agnostic LLM client interface."""

    @abstractmethod
    async def generate(self, system_prompt: str, user_message: str) -> str:
        """Send a prompt and return the raw text response."""
        ...


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


class MockLLMClient(LLMClient):
    """Mock client for testing — returns a preset response."""

    def __init__(self, response: str = ""):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        return self.response
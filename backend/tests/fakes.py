"""Client giả của SDK openai cho test, không gọi mạng."""

import json
from types import SimpleNamespace


class FakeResponses:
    """Giả lập `client.responses`: trả JSON cố định (hoặc ném `error`), ghi lại tham số của mỗi lần gọi."""

    def __init__(self, data: dict | None = None, error: Exception | None = None, raw: str | None = None):
        self.data, self.error, self.raw, self.calls = data or {}, error, raw, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            output_text=self.raw if self.raw is not None else json.dumps(self.data, ensure_ascii=False),
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )

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


def fake_usage(input_tokens=1000, output_tokens=50, cached=0, written=0, reasoning=0):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_tokens_details=SimpleNamespace(cached_tokens=cached, cache_write_tokens=written),
        output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning),
    )


class FakeStreamResponses:
    """Giả lập `client.responses` khi gọi với stream=True: phát các delta rồi sự kiện kết thúc."""

    def __init__(self, deltas: list[str], status: str = "completed", incomplete_reason: str | None = None,
                 error: Exception | None = None, usage=None):
        self.deltas, self.status, self.incomplete_reason, self.error = deltas, status, incomplete_reason, error
        self.usage = usage or fake_usage()
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self._events()

    async def _events(self):
        for delta in self.deltas:
            yield SimpleNamespace(type="response.output_text.delta", delta=delta)
        response = SimpleNamespace(
            status=self.status,
            usage=self.usage,
            incomplete_details=SimpleNamespace(reason=self.incomplete_reason) if self.incomplete_reason else None,
            error=None,
        )
        yield SimpleNamespace(type=f"response.{self.status}", response=response)

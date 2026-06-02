import pytest
from unittest.mock import MagicMock, patch
from csm_core.llm.client import LLMClient, make_client
from csm_core.llm.providers.mock import MockClient
from csm_core.llm.providers.anthropic import AnthropicClient
from csm_core.llm.providers.deepseek import DeepSeekClient


def test_mock_client_returns_fixed_response():
    client: LLMClient = MockClient(response="hello world")
    result = client.complete(system="sys", user="usr")
    assert result == "hello world"


def test_mock_client_records_calls():
    client = MockClient(response="ok")
    client.complete(system="S", user="U")
    # ``temperature`` defaults to ``None`` when caller didn't pass one —
    # provider implementations that skip it preserve legacy behaviour.
    assert client.calls == [{"system": "S", "user": "U", "temperature": None}]


def test_mock_client_records_temperature_override():
    client = MockClient(response="ok")
    client.complete(system="S", user="U", temperature=0.4)
    assert client.calls == [{"system": "S", "user": "U", "temperature": 0.4}]


def test_make_client_dispatches_by_provider():
    client = make_client(provider="mock", response="foo")
    assert isinstance(client, MockClient)


def test_make_client_unknown_provider_raises():
    with pytest.raises(ValueError, match="unknown provider"):
        make_client(provider="nonexistent")


def test_anthropic_client_reuses_sdk_across_calls():
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text="ok")]
    with patch("csm_core.llm.providers.anthropic.Anthropic") as fake_sdk:
        fake_sdk.return_value.messages.create.return_value = fake_response
        client = AnthropicClient(api_key="sk-x", model="claude-opus-4-7")
        client.complete(system="S", user="U")
        client.complete(system="S", user="U")
        # SDK should be constructed once per client, reused across complete() calls
        assert fake_sdk.call_count == 1


def test_anthropic_client_calls_sdk():
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text="Claude says hi")]
    with patch("csm_core.llm.providers.anthropic.Anthropic") as fake_sdk:
        fake_sdk.return_value.messages.create.return_value = fake_response
        client = AnthropicClient(api_key="sk-x", model="claude-opus-4-7")
        result = client.complete(system="S", user="U")
        assert result == "Claude says hi"
        fake_sdk.return_value.messages.create.assert_called_once()
        call_kwargs = fake_sdk.return_value.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "S"
        assert call_kwargs["messages"] == [{"role": "user", "content": "U"}]
        assert call_kwargs["model"] == "claude-opus-4-7"


def test_make_client_kimi_uses_moonshot_defaults():
    from csm_core.llm.providers.kimi import KimiClient
    client = make_client(provider="kimi", api_key="sk-k")
    assert isinstance(client, KimiClient)
    assert client.model == "kimi-k2.6"
    assert client.base_url == "https://api.moonshot.cn/v1"


def test_make_client_kimi_overrides():
    client = make_client(
        provider="kimi",
        api_key="sk-k",
        model="moonshot-v1-32k",
        base_url="https://proxy.example/v1",
    )
    assert client.api_key == "sk-k"
    assert client.model == "moonshot-v1-32k"
    assert client.base_url == "https://proxy.example/v1"


def test_make_client_doubao_uses_ark_defaults():
    from csm_core.llm.providers.doubao import DoubaoClient
    client = make_client(provider="doubao", api_key="sk-d")
    assert isinstance(client, DoubaoClient)
    assert client.model == "doubao-pro-32k"
    assert client.base_url == "https://ark.cn-beijing.volces.com/api/v3"


def test_make_client_doubao_overrides():
    client = make_client(
        provider="doubao",
        api_key="sk-d",
        model="ep-20240101-abcde",
        base_url="https://ark.cn-shanghai.volces.com/api/v3",
    )
    assert client.api_key == "sk-d"
    assert client.model == "ep-20240101-abcde"
    assert client.base_url == "https://ark.cn-shanghai.volces.com/api/v3"


def test_deepseek_client_calls_http(monkeypatch):
    class FakeResponse:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "DS says hi"}}]}
        def raise_for_status(self): pass

    class FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, **kw):
            self.last_kwargs = kw
            return FakeResponse()

    import csm_core.llm.providers.deepseek as mod
    monkeypatch.setattr(mod.httpx, "Client", FakeClient)
    client = DeepSeekClient(api_key="sk-y", model="deepseek-chat")
    result = client.complete(system="S", user="U")
    assert result == "DS says hi"


def test_openai_compat_retries_without_temperature_on_400(monkeypatch):
    """A reasoning model (e.g. kimi-k2.6) rejects a custom temperature with
    HTTP 400 "invalid temperature: only 1 is allowed for this model". The
    client should retry once with the ``temperature`` field stripped and
    succeed on the streamed second response."""
    import httpx as real_httpx
    import csm_core.llm.providers.openai_compat as mod

    sent_payloads: list[dict] = []

    class _FakeStreamResp:
        """Mimics the slice of httpx.Response the streaming code consumes:
        ``.status_code``, ``.read()`` (bytes), ``.iter_lines()`` (str), and
        ``.request`` (passed into HTTPStatusError)."""

        def __init__(self, status_code, *, body=b"", lines=()):
            self.status_code = status_code
            self._body = body
            self._lines = list(lines)
            self.request = real_httpx.Request("POST", "https://api.moonshot.cn/v1/chat/completions")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self._body

        def iter_lines(self):
            return iter(self._lines)

    class _FakeClient:
        # First call -> 400 temperature error; second (retry) -> 200 SSE stream.
        _responses = [
            _FakeStreamResp(
                400,
                body=b'{"error":{"message":"invalid temperature: only 1 is allowed for this model"}}',
            ),
            _FakeStreamResp(
                200,
                lines=[
                    'data: {"choices":[{"delta":{"content":"Hello"}}]}',
                    'data: {"choices":[{"delta":{"content":" world"}}]}',
                    "data: [DONE]",
                ],
            ),
        ]

        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, *, headers=None, json=None):
            # Snapshot the payload: complete() mutates the same dict in-place
            # (pop temperature) before the retry, so a live reference would
            # show both sends as the post-pop state.
            sent_payloads.append(dict(json))
            return self._responses.pop(0)

    monkeypatch.setattr(mod.httpx, "Client", _FakeClient)
    client = mod.OpenAICompatClient(
        api_key="sk-k", model="kimi-k2.6", base_url="https://api.moonshot.cn/v1"
    )
    # (1) it retried and succeeded — returns the concatenated stream
    result = client.complete(system="S", user="U", temperature=0.3)
    assert result == "Hello world"
    # Two requests went out: the original and the retry.
    assert len(sent_payloads) == 2
    # First request carried the rejected temperature...
    assert sent_payloads[0].get("temperature") == 0.3
    # (2) ...and the retry payload had NO temperature key.
    assert "temperature" not in sent_payloads[1]

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

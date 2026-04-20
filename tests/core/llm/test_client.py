import pytest
from csm_core.llm.client import LLMClient, make_client
from csm_core.llm.providers.mock import MockClient


def test_mock_client_returns_fixed_response():
    client: LLMClient = MockClient(response="hello world")
    result = client.complete(system="sys", user="usr")
    assert result == "hello world"


def test_mock_client_records_calls():
    client = MockClient(response="ok")
    client.complete(system="S", user="U")
    assert client.calls == [{"system": "S", "user": "U"}]


def test_make_client_dispatches_by_provider():
    client = make_client(provider="mock", response="foo")
    assert isinstance(client, MockClient)


def test_make_client_unknown_provider_raises():
    with pytest.raises(ValueError, match="unknown provider"):
        make_client(provider="nonexistent")

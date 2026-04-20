"""Mock LLM client for testing."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class MockClient:
    response: str = "mock response"
    calls: list[dict] = field(default_factory=list)

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        return self.response

"""Registry of available agent adapters."""

from .base import AgentAdapter
from .devin_cli import DevinCliAdapter

ADAPTERS: dict[str, type[AgentAdapter]] = {
    "devin-cli": DevinCliAdapter,
}


def get_adapter(name: str) -> AgentAdapter | None:
    adapter_cls = ADAPTERS.get(name)
    if adapter_cls is None:
        return None
    return adapter_cls()

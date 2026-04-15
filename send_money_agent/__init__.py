"""Send Money Agent package."""

from typing import Any

__all__ = ["root_agent"]


def __getattr__(name: str) -> Any:
    """
    Lazily expose root_agent so importing `send_money_agent.tools` in unit tests
    does not require importing ADK agent dependencies.
    """
    if name == "root_agent":
        from .agent import root_agent
        return root_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

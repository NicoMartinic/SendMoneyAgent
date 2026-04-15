"""
Run agent model-selection tests without requiring a real google-adk install.
Usage:
  pytest tests/test_agent.py -v
  python -m unittest tests/test_agent.py -v
"""

import importlib
import inspect
import os
import sys
import types
import unittest

# ── Minimal ADK mock ──────────────────────────────────────────────────────────
google_mod = types.ModuleType("google")
google_adk = types.ModuleType("google.adk")
google_adk_agents = types.ModuleType("google.adk.agents")
google_adk_tools = types.ModuleType("google.adk.tools")


class Agent:
    """Fake Agent capturing init kwargs."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


class ToolContext:
    """Fake ToolContext backed by a real dict."""

    def __init__(self):
        self.state: dict = {}


google_adk_agents.Agent = Agent
google_adk_tools.ToolContext = ToolContext
sys.modules["google"] = google_mod
sys.modules["google.adk"] = google_adk
sys.modules["google.adk.agents"] = google_adk_agents
sys.modules["google.adk.tools"] = google_adk_tools
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, ".")


class TestAgentModelSelection(unittest.TestCase):
    def setUp(self):
        self._original_model_env = os.environ.get("SEND_MONEY_MODEL")

    def tearDown(self):
        if self._original_model_env is None:
            os.environ.pop("SEND_MONEY_MODEL", None)
        else:
            os.environ["SEND_MONEY_MODEL"] = self._original_model_env
        sys.modules.pop("send_money_agent.agent", None)

    def _load_agent_module(self, model_env_value):
        if model_env_value is None:
            os.environ.pop("SEND_MONEY_MODEL", None)
        else:
            os.environ["SEND_MONEY_MODEL"] = model_env_value
        sys.modules.pop("send_money_agent.agent", None)
        return importlib.import_module("send_money_agent.agent")

    def test_default_alias_uses_gemini(self):
        agent_module = self._load_agent_module(None)
        self.assertEqual(agent_module.MODEL, "gemini-2.5-flash")
        self.assertEqual(agent_module.root_agent.model, "gemini-2.5-flash")

    def test_claude_alias_uses_provider_model(self):
        agent_module = self._load_agent_module("claude")
        self.assertEqual(agent_module.MODEL, "anthropic/claude-sonnet-4-6")
        self.assertEqual(agent_module.root_agent.model, "anthropic/claude-sonnet-4-6")

    def test_chatgpt_alias_uses_provider_model(self):
        agent_module = self._load_agent_module("chatgpt")
        self.assertEqual(agent_module.MODEL, "openai/gpt-5.4-mini")
        self.assertEqual(agent_module.root_agent.model, "openai/gpt-5.4-mini")

    def test_legacy_alias_gpt4_maps_to_supported_model(self):
        agent_module = self._load_agent_module("gpt4")
        self.assertEqual(agent_module.MODEL, "openai/gpt-5.4-mini")

    def test_legacy_litellm_prefix_is_normalized(self):
        agent_module = self._load_agent_module("litellm/openai/gpt-5.4-mini")
        self.assertEqual(agent_module.MODEL, "openai/gpt-5.4-mini")

    def test_normalize_model_strips_repeated_litellm_prefix(self):
        agent_module = self._load_agent_module("gemini")
        self.assertEqual(
            agent_module._normalize_model_name("litellm/litellm/anthropic/claude-sonnet-4-6"),
            "anthropic/claude-sonnet-4-6",
        )

    def test_instruction_requires_fresh_state_tokens_for_mutations(self):
        agent_module = self._load_agent_module("gemini")
        self.assertIn("Call `get_transfer_state` first.", agent_module.INSTRUCTION)
        self.assertIn("`read_token`", agent_module.INSTRUCTION)
        self.assertIn("`expected_version`", agent_module.INSTRUCTION)

    def test_mutating_tools_accept_read_contract_parameters(self):
        agent_module = self._load_agent_module("gemini")
        for tool in (
            agent_module.update_transfer_details,
            agent_module.confirm_transfer,
            agent_module.reset_transfer,
        ):
            params = inspect.signature(tool).parameters
            self.assertIn("read_token", params)
            self.assertIn("expected_version", params)

    def test_instruction_keeps_language_based_on_user_context(self):
        agent_module = self._load_agent_module("gemini")
        self.assertIn(
            "If it returns `active_language`, use that as the primary source of truth",
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            "If `active_language` is absent, fall back to the user's latest message and prior session context.",
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            "continue in the most recent clearly established language from the user",
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            "ask a brief clarifying question instead of guessing",
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            "Confirmation prompts and yes/no choices must stay in the user's active language too",
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            'If `active_language="en"`, do not answer in Spanish unless the user clearly switches to Spanish.',
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            'If `active_language="es"`, do not answer in English unless the user clearly switches to English.',
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            "si, confirmo, dale, adelante",
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            "Never strip a named currency from the user's message and assume the amount is USD.",
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            "If the user already supplied a valid delivery method in the same turn, include `delivery_method` immediately",
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            "Spanish delivery-method phrases such as `transferencia bancaria`, `retiro en efectivo`, `billetera móvil`, and `dinero móvil` count as provided delivery methods",
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            "max 2 decimal places",
            agent_module.INSTRUCTION,
        )

    def test_instruction_forbids_editing_confirmed_transfer(self):
        agent_module = self._load_agent_module("gemini")
        self.assertIn(
            "Do not call `update_transfer_details` to modify a confirmed transfer.",
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            "Never imply that an already confirmed transfer was changed.",
            agent_module.INSTRUCTION,
        )

    def test_instruction_requires_non_usd_amounts_to_be_reentered_in_usd(self):
        agent_module = self._load_agent_module("gemini")
        self.assertIn(
            "If the user gives an amount in a non-USD source currency, explain that send amounts must be entered in USD",
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            "pass `source_amount_currency` to `update_transfer_details` together with the amount",
            agent_module.INSTRUCTION,
        )
        self.assertIn(
            "If the user gives an amount with more than 2 decimal places, ask them to restate it with at most 2 decimals.",
            agent_module.INSTRUCTION,
        )


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

"""
Run CLI-focused tests without requiring real google-adk or litellm installs.
Usage:
  pytest tests/test_main.py -v
  python -m unittest tests.test_main -v
"""

import importlib
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


class FakePart:
    def __init__(self, text=None):
        self.text = text


class FakeContent:
    def __init__(self, role=None, parts=None):
        self.role = role
        self.parts = parts or []


class FakeEvent:
    def __init__(self, text):
        self.content = types.SimpleNamespace(parts=[types.SimpleNamespace(text=text)])

    def is_final_response(self):
        return True


class FakeRunner:
    last_instance = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        FakeRunner.last_instance = self

    async def run_async(self, **kwargs):
        self.calls.append(kwargs)
        yield FakeEvent("stub response")


class FakeSessionService:
    async def create_session(self, app_name, user_id):
        return types.SimpleNamespace(id="session-123")


def install_fake_modules(include_litellm=False):
    google_mod = types.ModuleType("google")
    google_adk = types.ModuleType("google.adk")
    google_adk_runners = types.ModuleType("google.adk.runners")
    google_adk_sessions = types.ModuleType("google.adk.sessions")
    google_genai = types.ModuleType("google.genai")
    google_genai_types = types.ModuleType("google.genai.types")

    google_adk_runners.Runner = FakeRunner
    google_adk_sessions.InMemorySessionService = FakeSessionService
    google_genai_types.Content = FakeContent
    google_genai_types.Part = FakePart

    google_mod.adk = google_adk
    google_mod.genai = google_genai
    google_adk.runners = google_adk_runners
    google_adk.sessions = google_adk_sessions
    google_genai.types = google_genai_types

    sys.modules["google"] = google_mod
    sys.modules["google.adk"] = google_adk
    sys.modules["google.adk.runners"] = google_adk_runners
    sys.modules["google.adk.sessions"] = google_adk_sessions
    sys.modules["google.genai"] = google_genai
    sys.modules["google.genai.types"] = google_genai_types

    fake_send_money_agent = types.ModuleType("send_money_agent")
    fake_send_money_agent.root_agent = object()
    sys.modules["send_money_agent"] = fake_send_money_agent

    if include_litellm:
        fake_litellm = types.ModuleType("litellm")
        fake_litellm.suppress_debug_info = False
        sys.modules["litellm"] = fake_litellm
    else:
        sys.modules.pop("litellm", None)


class TestMainCli(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "google",
                "google.adk",
                "google.adk.runners",
                "google.adk.sessions",
                "google.genai",
                "google.genai.types",
                "litellm",
                "main",
                "send_money_agent",
            )
        }
        sys.path.insert(0, ".")

    def tearDown(self):
        if sys.path and sys.path[0] == ".":
            sys.path.pop(0)
        for name, module in self._saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        FakeRunner.last_instance = None

    def _load_main(self, include_litellm=False):
        install_fake_modules(include_litellm=include_litellm)
        sys.modules.pop("main", None)
        return importlib.import_module("main")

    def test_detect_active_language_english_sentence(self):
        main_module = self._load_main()
        self.assertEqual(
            main_module.detect_active_language("I want to send money to Maria.", None),
            "en",
        )

    def test_detect_active_language_spanish_sentence(self):
        main_module = self._load_main()
        self.assertEqual(
            main_module.detect_active_language("Quiero enviar dinero a Maria.", None),
            "es",
        )

    def test_detect_active_language_ambiguous_short_reply_reuses_english(self):
        main_module = self._load_main()
        self.assertEqual(main_module.detect_active_language("ok", "en"), "en")

    def test_detect_active_language_ambiguous_short_reply_reuses_spanish(self):
        main_module = self._load_main()
        self.assertEqual(main_module.detect_active_language("ok", "es"), "es")

    def test_detect_active_language_ambiguous_short_reply_without_history_is_none(self):
        main_module = self._load_main()
        self.assertIsNone(main_module.detect_active_language("ok", None))

    async def test_run_cli_passes_state_delta_when_language_is_known(self):
        main_module = self._load_main()
        stdout = io.StringIO()
        with patch("builtins.input", side_effect=["I want to send money to Maria.", "quit"]):
            with redirect_stdout(stdout):
                await main_module.run_cli(None)

        self.assertIsNotNone(FakeRunner.last_instance)
        self.assertEqual(
            FakeRunner.last_instance.calls[0]["state_delta"],
            {"active_language": "en"},
        )

    def test_suppress_litellm_debug_info_sets_flag_when_module_is_available(self):
        main_module = self._load_main(include_litellm=True)
        litellm_module = sys.modules["litellm"]
        self.assertFalse(litellm_module.suppress_debug_info)
        self.assertTrue(main_module.suppress_litellm_debug_info())
        self.assertTrue(litellm_module.suppress_debug_info)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

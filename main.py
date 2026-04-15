"""
CLI runner for the Send Money Agent.

Usage:
    python main.py                      # uses SEND_MONEY_MODEL env var (default: gemini)
    python main.py --model claude       # Anthropic Claude
    python main.py --model chatgpt      # OpenAI GPT-5.4 mini
    python main.py --model gemini       # Google Gemini (default)

    # Or use the ADK built-in web UI:
    adk web
"""

import asyncio
import argparse
import os
import re
import sys
import unicodedata

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

_ENGLISH_LANGUAGE_MARKERS = {
    "amount",
    "bank",
    "cash",
    "confirm",
    "country",
    "delivery",
    "help",
    "money",
    "name",
    "recipient",
    "reset",
    "send",
    "start",
    "transfer",
    "wallet",
    "yes",
}

_SPANISH_LANGUAGE_MARKERS = {
    "adelante",
    "ayuda",
    "cantidad",
    "confirma",
    "confirmo",
    "dale",
    "dinero",
    "efectivo",
    "enviar",
    "monto",
    "nombre",
    "pais",
    "por",
    "reiniciar",
    "si",
    "transferencia",
}

_ENGLISH_LANGUAGE_PHRASES = (
    "bank transfer",
    "cash pickup",
    "go ahead",
    "send money",
    "start over",
)

_SPANISH_LANGUAGE_PHRASES = (
    "enviar dinero",
    "por favor",
    "retiro en efectivo",
    "transferencia bancaria",
    "quiero enviar",
)


def _normalize_language_text(user_text: str) -> str:
    lowered = user_text.strip().lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def detect_active_language(user_text: str, previous_language: str | None) -> str | None:
    """Return `en`, `es`, or the prior language when the current input is ambiguous."""
    normalized = _normalize_language_text(user_text)
    tokens = re.findall(r"[a-z]+", normalized)

    english_score = sum(token in _ENGLISH_LANGUAGE_MARKERS for token in tokens)
    spanish_score = sum(token in _SPANISH_LANGUAGE_MARKERS for token in tokens)

    english_score += sum(phrase in normalized for phrase in _ENGLISH_LANGUAGE_PHRASES)
    spanish_score += sum(phrase in normalized for phrase in _SPANISH_LANGUAGE_PHRASES)

    if any(ch in user_text for ch in "¿¡ñÑáéíóúÁÉÍÓÚ"):
        spanish_score += 1

    if english_score > spanish_score:
        return "en"
    if spanish_score > english_score:
        return "es"

    if previous_language in {"en", "es"}:
        return previous_language
    return None


def suppress_litellm_debug_info() -> bool:
    """Best-effort suppression of LiteLLM dependency noise in the CLI."""
    try:
        import litellm
    except ImportError:
        return False

    litellm.suppress_debug_info = True
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send Money Agent CLI")
    parser.add_argument(
        "--model",
        choices=[
            "gemini",
            "gemini_pro",
            "claude",
            "claude_opus",
            "chatgpt",
            "gpt54",
            "gpt54mini",
            "gpt5",
            # Backward-compatible legacy aliases
            "gpt4",
            "gpt4o",
        ],
        default=None,
        help="LLM backend to use (overrides SEND_MONEY_MODEL env var)",
    )
    return parser.parse_args()


async def run_cli(model: str | None) -> None:
    # Set model env before importing the agent (agent reads it at import time)
    if model:
        os.environ["SEND_MONEY_MODEL"] = model

    suppress_litellm_debug_info()

    # Import after env is set
    from send_money_agent import root_agent

    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="send_money_app",
        user_id="cli_user",
    )

    runner = Runner(
        agent=root_agent,
        app_name="send_money_app",
        session_service=session_service,
    )

    active_model = os.environ.get("SEND_MONEY_MODEL", "gemini")
    print(f"\n{'='*55}")
    print(f"  💸  Send Money Agent  |  model: {active_model}")
    print(f"{'='*55}")
    print("  Type your message and press Enter.")
    print("  Commands: 'quit' or 'exit' to leave, 'reset' to start over.")
    print(f"{'='*55}\n")

    active_language: str | None = None

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit"}:
            print("Goodbye!")
            break

        message = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=user_input)],
        )
        active_language = detect_active_language(user_input, active_language)

        run_kwargs = {
            "user_id": "cli_user",
            "session_id": session.id,
            "new_message": message,
        }
        if active_language is not None:
            run_kwargs["state_delta"] = {"active_language": active_language}

        print("\nAgent: ", end="", flush=True)
        async for event in runner.run_async(**run_kwargs):
            if event.is_final_response() and event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        print(part.text)
        print()


def main() -> None:
    args = parse_args()
    asyncio.run(run_cli(args.model))


if __name__ == "__main__":
    main()

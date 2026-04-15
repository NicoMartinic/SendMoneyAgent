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
import sys

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types


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

        print("\nAgent: ", end="", flush=True)
        async for event in runner.run_async(
            user_id="cli_user",
            session_id=session.id,
            new_message=message,
        ):
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

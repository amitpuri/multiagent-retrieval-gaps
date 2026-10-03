"""
MAF model/client provider — selects the right AgentFactory client based on
available credentials, in priority order:

  1. Azure AI Foundry   (AZURE_AI_FOUNDRY_PROJECT_ENDPOINT)
  2. Azure OpenAI       (AZURE_OPENAI_ENDPOINT)
  3. OpenAI Agents SDK  (OPENAI_API_KEY)  ← active for local testing via src/.env
  4. Offline mock       (MAF_OFFLINE_MODE=true or no credentials)
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Load src/.env automatically so tests and runner both pick up credentials
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=False)


def build_agent_factory(
    offline: bool = False,
    bindings: dict | None = None,
    safe_mode: bool = False,
):
    """Return an AgentFactory configured for the best available credential."""
    # Import here so the module is importable even without MAF installed
    try:
        from agent_framework.declarative import AgentFactory
    except ImportError as exc:
        raise ImportError(
            "agent-framework-declarative is not installed. "
            "Run: pip install agent-framework-declarative"
        ) from exc

    # ── Offline / CI mode ───────────────────────────────────────────────────
    if offline or os.getenv("MAF_OFFLINE_MODE", "false").lower() in ("true", "1", "yes"):
        return AgentFactory(bindings=bindings, safe_mode=safe_mode)

    # ── Option A: Azure AI Foundry ──────────────────────────────────────────
    if os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"):
        from azure.identity import AzureCliCredential
        try:
            from agent_framework.foundry import FoundryChatClient
            credential = AzureCliCredential()
            client = FoundryChatClient(
                endpoint=os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"],
                credential=credential,
            )
            return AgentFactory(client=client, bindings=bindings, safe_mode=safe_mode)
        except ImportError as exc:
            raise ImportError(
                "agent-framework-foundry is not installed. "
                "Run: pip install agent-framework-foundry"
            ) from exc

    # ── Option B: Azure OpenAI direct ──────────────────────────────────────
    if os.getenv("AZURE_OPENAI_ENDPOINT"):
        from azure.identity import AzureCliCredential
        return AgentFactory(credential=AzureCliCredential(), bindings=bindings, safe_mode=safe_mode)

    # ── Option C: OpenAI Agents SDK (local fallback) ────────────────────────
    # Active when only OPENAI_API_KEY is present (e.g. src/.env in this repo)
    if os.getenv("OPENAI_API_KEY"):
        try:
            from agent_framework.openai import OpenAIChatClient
            model = os.getenv("OPENAI_MODEL", "gpt-5")
            client = OpenAIChatClient(model=model, api_key=os.environ["OPENAI_API_KEY"])
            return AgentFactory(client=client, bindings=bindings, safe_mode=safe_mode)
        except ImportError:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
                return AgentFactory(client=client, bindings=bindings, safe_mode=safe_mode)
            except ImportError as exc:
                raise ImportError(
                    "Neither agent-framework-openai nor openai package is installed. "
                    "Run: pip install agent-framework-openai"
                ) from exc

    raise RuntimeError(
        "No credentials found.\n"
        "Set one of:\n"
        "  AZURE_AI_FOUNDRY_PROJECT_ENDPOINT  (Azure AI Foundry — production)\n"
        "  AZURE_OPENAI_ENDPOINT              (Azure OpenAI — direct)\n"
        "  OPENAI_API_KEY                     (OpenAI Agents SDK — local/fallback)\n"
        "  MAF_OFFLINE_MODE=true              (offline mock — no API calls)\n"
        "in src/.env or environment."
    )

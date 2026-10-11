"""
Model provider factory for Strands Agents SDK.
Uses Anthropic Claude (via direct Anthropic API key from .env or AWS Bedrock)
or deterministic MockBedrockModel for offline execution.
LiteLLM, Gemini, and OpenAI are strictly excluded.
"""
import os
import sys
from pathlib import Path
from typing import Any, Optional
from collections.abc import AsyncGenerator
from dotenv import load_dotenv

# Auto-load local .env if present
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

from strands.models.model import Model

# Model IDs come from config/models.yaml (single source of truth across clouds).
from ontogate.catalog import load_catalog, model_for  # noqa: E402

_AWS = model_for("aws")
DEFAULT_CLAUDE_MODEL_ID = _AWS["anthropic_id"]
DEFAULT_BEDROCK_CLAUDE_MODEL_ID = _AWS["bedrock_id"]
OFFLINE_MODEL_ID = load_catalog()["offline"]["aws"]


def claude_request_fields(role: str = "") -> dict:
    """Per-role request fields for current Claude models.

    Thinking cannot be disabled on Claude Opus 5.5 and effort defaults to
    "medium", so effort is always sent explicitly (config/models.yaml).
    """
    return {"output_config": {"effort": model_for("aws", role)["effort"]}}


class MockBedrockModel(Model):
    """Deterministic offline model for tests, CI, and local execution without API keys."""

    def __init__(self, response_text: str = ""):
        self.response_text = response_text or (
            "[CLAUDE GROUNDED CLINICAL INTERPRETATION]\n"
            "LOINC: loinc:718-7 (Hemoglobin [Mass/volume] in Blood - Hematology)\n"
            "Reference Range: 13.8-17.2 g/dL (Adult Male)\n"
            "Panic Limits: Critical Low < 7.0 g/dL | Critical High > 20.0 g/dL\n"
            "Patient Result: Grounded calibrated evaluation completed per clinical guidelines."
        )

    def get_config(self) -> dict[str, Any]:
        return {"model_id": OFFLINE_MODEL_ID}

    def update_config(self, **kwargs: Any) -> None:
        pass

    def structured_output(self, *args: Any, **kwargs: Any) -> Any:
        return None

    async def stream(
        self,
        messages: Any,
        tool_specs: Any = None,
        system_prompt: Any = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockDelta": {"delta": {"text": self.response_text}}}
        yield {"messageStop": {"stopReason": "end_turn"}}


def is_offline_mode(offline: Optional[bool] = None) -> bool:
    """Check if offline/mock mode should be activated."""
    if offline is not None:
        return offline
    if "--offline" in sys.argv:
        return True
    if os.environ.get("STRANDS_OFFLINE_MODE", "").lower() in ("true", "1", "yes"):
        return True
    # If neither Anthropic API key nor AWS Bedrock is configured, default to offline
    has_anthropic_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_aws_env = bool(
        (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))
        and (os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"))
    )
    return not (has_anthropic_key or has_aws_env)


def get_strands_model(offline: Optional[bool] = None, response_text: str = "", role: str = "") -> Model:
    """Return Anthropic Claude (via ANTHROPIC_API_KEY or AWS Bedrock) or MockBedrockModel if offline.

    Strictly no LiteLLM, no Gemini, no OpenAI.
    """
    if is_offline_mode(offline):
        return MockBedrockModel(response_text=response_text)

    # 1. Prefer direct Anthropic Claude if ANTHROPIC_API_KEY is configured in .env
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from strands.models.anthropic import AnthropicModel

            model_id = os.environ.get("ANTHROPIC_MODEL_ID", DEFAULT_CLAUDE_MODEL_ID)
            max_tokens = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "2048"))
            return AnthropicModel(model_id=model_id, max_tokens=max_tokens, params=claude_request_fields(role))
        except Exception as e:
            print(f"[Warning] Failed to initialize AnthropicModel: {e}")

    # 2. AWS Bedrock Claude if AWS environment is configured
    try:
        from strands.models import BedrockModel

        model_id = os.environ.get("BEDROCK_MODEL_ID", DEFAULT_BEDROCK_CLAUDE_MODEL_ID)
        region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        return BedrockModel(model_id=model_id, region_name=region,
                            additional_request_fields=claude_request_fields(role))
    except Exception as e:
        print(f"[Warning] Failed to initialize BedrockModel: {e}")

    # 3. Fallback to mock
    return MockBedrockModel(response_text=response_text)

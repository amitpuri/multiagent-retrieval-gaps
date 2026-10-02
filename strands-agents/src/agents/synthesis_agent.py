"""
Clinical Synthesis Agent using Strands Agents SDK.
Synthesizes calibrated, grounded clinical interpretations powered by Anthropic Claude on AWS Bedrock.
"""
from typing import Optional
from strands import Agent
from strands.models.model import Model


def create_synthesis_agent(model: Optional[Model] = None) -> Agent:
    """Create a Clinical Synthesis Agent."""
    return Agent(
        model=model,
        system_prompt=(
            "You are a Clinical Laboratory Synthesis Specialist.\n"
            "Your task is to provide a grounded, rigorous clinical interpretation of the patient's lab result "
            "strictly using the verified LOINC concept and protocol reference ranges provided in the prompt.\n"
            "Rules:\n"
            "1. State the exact canonical LOINC code and concept name.\n"
            "2. Compare the patient value against the reference range and explicit panic limits.\n"
            "3. State clearly whether the value is Normal, Elevated, Low, or a Panic/Critical Alert.\n"
            "4. Never extrapolate or recommend diagnostic treatments outside the provided guideline."
        ),
        tools=[],  # Synthesis reasons directly over the provided structured clinical context
    )

"""
Clinical Synthesis Agent: Calibrated interpretation synthesis without hallucination.
Single-turn ADK Agent grounded strictly on protocol data provided in the input payload.
"""

from typing import Optional
from google.adk import Agent

DEFAULT_MODEL = "gemini-3.5-flash"


def create_synthesize_agent(model: Optional[str] = None) -> Agent:
    """Create single-turn synthesis agent for clinical interpretations."""
    chosen_model = model or DEFAULT_MODEL
    return Agent(
        name="clinical_synthesizer",
        model=chosen_model,
        mode="single_turn",
        instruction=(
            "You are a clinical laboratory specialist. Interpret the patient's value "
            "using ONLY the protocol data provided in the input. Name the resolved LOINC "
            "concept, cite the reference range and panic limits, and provide a calibrated, "
            "cautious interpretation. Never speculate beyond the provided protocol."
        ),
    )

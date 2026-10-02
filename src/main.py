"""
Main CLI entry point for executing the ADK laboratory decision support demo.
Runs the pure code test assertions first, followed by the scenario workflows.
"""

import asyncio
import sys
from src.runner import main as run_scenarios


def main():
    print("================================================================================")
    print("   Information Retrieval, Part III: When the Retriever Has to Decide")
    print("   Google ADK 2.0 & Clinical Ontology Decision Support")
    print("================================================================================\n")
    asyncio.run(run_scenarios())


if __name__ == "__main__":
    main()

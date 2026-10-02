"""
Main CLI entry point for executing the Strands & Amazon Bedrock AgentCore laboratory decision support demo.
Runs the clinical decision scenarios across Scenarios A through D.
"""
import asyncio
from pathlib import Path
import sys

# Configure UTF-8 encoding for standard streams (especially on Windows)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure repository root and strands-agents root are on sys.path
strands_agents_dir = Path(__file__).resolve().parent.parent
repo_root = strands_agents_dir.parent

# Ensure repository root is on sys.path, with strands-agents first
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
if str(strands_agents_dir) in sys.path:
    sys.path.remove(str(strands_agents_dir))
sys.path.insert(0, str(strands_agents_dir))

from src.runner import main as run_scenarios


def main():
    print("=" * 80)
    print("   Information Retrieval, Part III: When the Retriever Has to Decide")
    print("   AWS Strands Agents SDK & Amazon Bedrock AgentCore Implementation")
    print("   Powered by Anthropic Claude on AWS Bedrock (No LiteLLM / Gemini)")
    print("=" * 80 + "\n")
    asyncio.run(run_scenarios())


if __name__ == "__main__":
    main()

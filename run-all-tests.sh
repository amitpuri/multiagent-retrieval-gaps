#!/usr/bin/env bash
# Offline verification: knowledge integrity, skills, generated artifacts, every
# framework's tests and cross-cloud conformance. No cloud credentials needed.
# Prerequisite: pip install -e "shared[dev]" plus each framework's requirements.txt.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="${PWD}/shared${PYTHONPATH:+:${PYTHONPATH}}"

echo "=== Ontology integrity (pack + scenario overlays) ==="
python -m ontogate validate

echo "=== Runtime skills: lint, role checks, reference and lock drift ==="
python -m ontogate skills check

echo "=== SHACL over the ontology and the agent meta-graph ==="
python -m ontogate rdf validate
python -m ontogate rdf validate --domain cardiology

echo "=== Developer skills mirror (.claude/skills) ==="
python -m ontogate skills mirror --check

echo "=== MAF declarative agents match the role specs ==="
(cd agent-framework && python -m src.declarative --check)

echo "=== shared (ontogate) tests ==="
python -m pytest shared/tests

echo "=== google-adk-agents tests ==="
python -m pytest google-adk-agents/tests

echo "=== strands-agents tests ==="
python -m pytest strands-agents/tests

echo "=== agent-framework tests ==="
python -m pytest agent-framework/tests

echo "=== Deployment teardown (ledger, handlers, script coverage) ==="
python -m pytest deployment/tests

echo "=== Cross-cloud conformance (ADK / Strands / MAF), AgentCards and live runner ==="
python -m pytest conformance

echo "=== Answer graders (P13.3) ==="
python -m pytest evals

echo "=== All checks passed ==="

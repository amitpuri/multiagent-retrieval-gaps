#!/usr/bin/env bash
set -euo pipefail

echo "=== Running google-adk-agents tests ==="
python -m pytest google-adk-agents/tests

echo "=== Running strands-agents tests ==="
python -m pytest strands-agents/tests

echo "=== Running agent-framework tests ==="
python -m pytest agent-framework/tests

echo "=== All test suites passed! ==="
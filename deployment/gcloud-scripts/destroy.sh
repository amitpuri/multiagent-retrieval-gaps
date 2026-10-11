#!/usr/bin/env bash
# ==============================================================================
# Teardown for the Google Cloud deployment.
#
# Deletes exactly the resources deploy.sh created (recorded in .deployed/ledger.tsv),
# newest first, via deployment/teardown.py. Prints the plan unless --yes is given.
#   ./destroy.sh               # plan only
#   ./destroy.sh --yes         # delete (--force is accepted as an alias)
#   ./destroy.sh --discover    # a deployment made before the ledger existed
# ==============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/config.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/config.env"
  set +a
fi
export PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
ARGS=()
for arg in "$@"; do
  case "${arg}" in
    --force|-f) ARGS+=(--yes) ;;
    *) ARGS+=("${arg}") ;;
  esac
done
exec python "${SCRIPT_DIR}/../teardown.py" gcp ${ARGS[@]+"${ARGS[@]}"}

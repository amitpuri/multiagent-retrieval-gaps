"""
Deploy the Google ADK workflow to Vertex AI Agent Engine (Agent Runtime) as a
native ``AdkApp`` — the ADK agent itself, not a wrapper around it.

The agent is packaged self-contained: the ADK ``src`` package, the shared
``ontogate`` core and the knowledge release it serves (``ontology/``,
``config/``, ``skills/``) are staged into one directory, so the runtime
resolves the same pinned bundle and skills lock as every other cloud.

    python deployment/gcloud-scripts/agent_runtime.py --dry-run        # stage + import check, offline
    python deployment/gcloud-scripts/agent_runtime.py --project P --location europe-west1 \\
        --staging-bucket gs://P-agent-staging

Deploying creates billable resources in the named project; deploy.sh asks for
it explicitly (--use-agent-runtime) and records the resource so that
``destroy.sh --yes`` deletes it.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parents[2]
STAGED = {  # staged name -> source
    "src": REPO / "google-adk-agents" / "src",
    "ontogate": REPO / "shared" / "ontogate",
    "ontology": REPO / "ontology",
    "config": REPO / "config",
    "skills": REPO / "skills",
    "agents": REPO / "agents",
}
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".env", "*.env", ".pytest_cache")


def stage(dest: Path) -> List[str]:
    """Copy the agent and its knowledge release into ``dest``; return the extra_packages list."""
    dest.mkdir(parents=True, exist_ok=True)
    for name, source in STAGED.items():
        shutil.copytree(source, dest / name, ignore=_IGNORE)
    return list(STAGED)


def requirements() -> List[str]:
    """Runtime requirements from google-adk-agents/requirements.txt (no test tooling, no local paths)."""
    reqs = []
    for line in (REPO / "google-adk-agents" / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith(("-", ".", "/")) and not line.lower().startswith(("pytest", "rdflib",
                                                                                          "pyshacl", "owlrl")):
            reqs.append(line)
    return reqs


def check_import(stage_dir: Path) -> None:
    """Import the staged agent in a clean interpreter (proves the package is self-contained)."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "ONTOGATE_REPO_ROOT")}
    code = ("import sys; sys.path.insert(0, '.'); from src.workflow import root_agent; "
            "from ontogate.release import verify_release; from ontogate.skills import verify_skills_lock; "
            "verify_skills_lock(); print(root_agent.name, verify_release()['bundle_sha256'])")
    proc = subprocess.run([sys.executable, "-I", "-c", code], cwd=stage_dir, env=env,
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise SystemExit(f"Staged agent does not import cleanly:\n{proc.stderr[-3000:]}")
    print(f"[+] Staged agent imports cleanly: {proc.stdout.strip().splitlines()[-1]}")


def deploy(stage_dir: Path, args: argparse.Namespace, packages: List[str]) -> str:
    import vertexai
    from vertexai import agent_engines

    os.chdir(stage_dir)
    sys.path.insert(0, str(stage_dir))
    from ontogate.release import current_release
    from src.workflow import root_agent

    client = vertexai.Client(project=args.project, location=args.location)
    app = agent_engines.AdkApp(agent=root_agent, enable_tracing=True)
    config = {
        "display_name": args.display_name,
        "description": "Clinical decision support: Google ADK on Agent Runtime, ontology-gated.",
        "staging_bucket": args.staging_bucket,
        "requirements": requirements(),
        "extra_packages": packages,
        "env_vars": {
            "GOOGLE_GENAI_USE_VERTEXAI": "true",
            "ONTOGATE_BUNDLE_SHA256": current_release()["bundle_sha256"],
        },
    }
    if args.service_account:
        config["service_account"] = args.service_account
    remote = client.agent_engines.create(agent=app, config=config)
    return remote.api_resource.name


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project")
    parser.add_argument("--location", default="europe-west1")
    parser.add_argument("--staging-bucket")
    parser.add_argument("--display-name", default="Clinical Decision Support Agent")
    parser.add_argument("--service-account")
    parser.add_argument("--dry-run", action="store_true", help="stage and import-check only; deploy nothing")
    parser.add_argument("--ledger", help="teardown ledger to record the created resource in (deploy.sh passes it)")
    args = parser.parse_args(argv)
    if not args.dry_run and not (args.project and args.staging_bucket):
        parser.error("--project and --staging-bucket are required unless --dry-run")

    with tempfile.TemporaryDirectory(prefix="adk-agent-runtime-") as tmp:
        stage_dir = Path(tmp)
        packages = stage(stage_dir)
        check_import(stage_dir)
        if args.dry_run:
            print(f"[i] Dry run: would deploy {packages} with {len(requirements())} requirement(s)")
            return 0
        name = deploy(stage_dir, args, packages)
        os.chdir(REPO)
    if args.ledger:  # deployment/teardown.py deletes it with `destroy.sh --yes`
        ledger = Path(args.ledger)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(f"agent-runtime\t{name}\tlocation={args.location};project={args.project}\n")
    print(f"[+] Agent Runtime resource: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

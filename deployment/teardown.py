"""
Teardown for every cloud deployment — so nothing keeps billing after a demo.

Each deploy script appends every resource it CREATES to a ledger
(``deployment/<cloud>-scripts/.deployed/ledger.tsv``, one line per resource:
``kind<TAB>name<TAB>key=value;key=value``). Resources the deploy merely reused
(an existing Foundry account, a pre-existing bucket) are never recorded, so
teardown never deletes what it did not create.

    python deployment/teardown.py gcp            # plan: print what would be deleted (default)
    python deployment/teardown.py gcp --yes      # delete, newest first; keep failures in the ledger
    python deployment/teardown.py aws --discover # no ledger (older deploy): find default-named resources

``destroy.sh`` / ``destroy.ps1`` in each cloud folder call this script.
After deleting, it lists what can still incur cost and is not deployment-owned
(images in a shared registry, build buckets, user-provisioned skill stores).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

HERE = Path(__file__).resolve().parent
CLOUD_DIRS = {"gcp": "gcloud-scripts", "aws": "aws-scripts", "azure": "az-scripts"}


@dataclass
class Resource:
    kind: str
    name: str
    attrs: Dict[str, str] = field(default_factory=dict)

    def line(self) -> str:
        return "\t".join([self.kind, self.name, ";".join(f"{k}={v}" for k, v in sorted(self.attrs.items()))])

    @classmethod
    def parse(cls, line: str) -> "Resource":
        kind, name, *rest = line.rstrip("\r\n").split("\t")
        attrs = dict(kv.split("=", 1) for kv in (rest[0].split(";") if rest and rest[0] else []) if "=" in kv)
        return cls(kind, name, attrs)

    def __str__(self) -> str:
        extra = ", ".join(f"{k}={v}" for k, v in sorted(self.attrs.items()))
        return f"{self.kind} {self.name}" + (f" ({extra})" if extra else "")


class Runner:
    """Runs CLI commands; ``capture`` returns stdout (empty on failure)."""

    def run(self, argv: Sequence[str]) -> bool:
        print("    $ " + " ".join(argv))
        return subprocess.run(list(argv), shell=sys.platform == "win32").returncode == 0

    def capture(self, argv: Sequence[str]) -> str:
        proc = subprocess.run(list(argv), capture_output=True, text=True, shell=sys.platform == "win32")
        return proc.stdout if proc.returncode == 0 else ""


Step = List[str]
Handler = Callable[[Resource, Runner], List[Step]]


def _a(r: Resource, key: str, default: str = "") -> str:
    return r.attrs.get(key, default)


# --------------------------------------------------------------------------- GCP
def _gcp_agent_runtime(r: Resource, runner: Runner) -> List[Step]:
    # Agent Runtime (Vertex AI Agent Engine) resources are deleted through the SDK.
    code = ("import vertexai,sys; c=vertexai.Client(project=sys.argv[1], location=sys.argv[2]); "
            "c.agent_engines.delete(name=sys.argv[3], force=True)")
    return [[sys.executable, "-c", code, _a(r, "project"), _a(r, "location"), r.name]]


GCP: Dict[str, Handler] = {
    "agent-runtime": _gcp_agent_runtime,
    "cloud-run-service": lambda r, _: [["gcloud", "run", "services", "delete", r.name, f"--region={_a(r, 'region')}",
                                        f"--project={_a(r, 'project')}", "--quiet"]],
    "secret": lambda r, _: [["gcloud", "secrets", "delete", r.name, f"--project={_a(r, 'project')}", "--quiet"]],
    "artifact-repository": lambda r, _: [["gcloud", "artifacts", "repositories", "delete", r.name,
                                          f"--location={_a(r, 'location')}", f"--project={_a(r, 'project')}", "--quiet"]],
    # Project IAM grants cost nothing and may pre-date the deploy: reported, removed only on request.
    "iam-binding": lambda r, _: [["gcloud", "projects", "remove-iam-policy-binding", _a(r, "project"),
                                  f"--member={r.name}", f"--role={_a(r, 'role')}", "--quiet"]],
}


# --------------------------------------------------------------------------- AWS
def _aws_runtime(r: Resource, runner: Runner) -> List[Step]:
    region = _a(r, "region")
    steps = [["aws", "bedrock-agentcore-control", "delete-agent-runtime", "--agent-runtime-id", r.name,
              "--region", region]]
    # The runtime writes logs to /aws/bedrock-agentcore/runtimes/<id>-<endpoint>; log storage keeps billing.
    out = runner.capture(["aws", "logs", "describe-log-groups", "--log-group-name-prefix",
                          f"/aws/bedrock-agentcore/runtimes/{r.name}", "--region", region,
                          "--query", "logGroups[].logGroupName", "--output", "json"])
    for group in json.loads(out or "[]"):
        steps.append(["aws", "logs", "delete-log-group", "--log-group-name", group, "--region", region])
    return steps


def _aws_role(r: Resource, runner: Runner) -> List[Step]:
    out = runner.capture(["aws", "iam", "list-role-policies", "--role-name", r.name,
                          "--query", "PolicyNames", "--output", "json"])
    steps = [["aws", "iam", "delete-role-policy", "--role-name", r.name, "--policy-name", p]
             for p in json.loads(out or "[]")]
    return steps + [["aws", "iam", "delete-role", "--role-name", r.name]]


AWS: Dict[str, Handler] = {
    "agentcore-runtime": _aws_runtime,
    "agentcore-memory": lambda r, _: [["aws", "bedrock-agentcore-control", "delete-memory", "--memory-id", r.name,
                                       "--region", _a(r, "region")]],
    "app-runner-service": lambda r, _: [["aws", "apprunner", "delete-service", "--service-arn", r.name,
                                         "--region", _a(r, "region")]],
    "ecr-repository": lambda r, _: [["aws", "ecr", "delete-repository", "--repository-name", r.name, "--force",
                                     "--region", _a(r, "region")]],
    "iam-role": _aws_role,
    "cloudformation-stack": lambda r, _: [
        ["aws", "cloudformation", "delete-stack", "--stack-name", r.name, "--region", _a(r, "region")],
        ["aws", "cloudformation", "wait", "stack-delete-complete", "--stack-name", r.name, "--region", _a(r, "region")]],
}


# --------------------------------------------------------------------------- Azure
AZURE: Dict[str, Handler] = {
    "role-assignment": lambda r, _: [["az", "role", "assignment", "delete", "--ids", r.name]],
    "container-app": lambda r, _: [["az", "containerapp", "delete", "--name", r.name,
                                    "--resource-group", _a(r, "resource_group"), "--yes"]],
    "containerapp-env": lambda r, _: [["az", "containerapp", "env", "delete", "--name", r.name,
                                       "--resource-group", _a(r, "resource_group"), "--yes"]],
    "log-analytics-workspace": lambda r, _: [["az", "monitor", "log-analytics", "workspace", "delete",
                                              "--workspace-name", r.name, "--resource-group", _a(r, "resource_group"),
                                              "--yes", "--force"]],
    "acr": lambda r, _: [["az", "acr", "delete", "--name", r.name, "--resource-group", _a(r, "resource_group"), "--yes"]],
    "foundry-model-deployment": lambda r, _: [["az", "cognitiveservices", "account", "deployment", "delete",
                                               "--name", _a(r, "account"), "--resource-group", _a(r, "resource_group"),
                                               "--deployment-name", r.name]],
    "foundry-project": lambda r, _: [["az", "cognitiveservices", "account", "project", "delete",
                                      "--name", _a(r, "account"), "--resource-group", _a(r, "resource_group"),
                                      "--project-name", r.name]],
    # Cognitive Services accounts are soft-deleted; purge so the name and quota are released.
    "foundry-account": lambda r, _: [
        ["az", "cognitiveservices", "account", "delete", "--name", r.name, "--resource-group", _a(r, "resource_group")],
        ["az", "cognitiveservices", "account", "purge", "--name", r.name, "--resource-group", _a(r, "resource_group"),
         "--location", _a(r, "location")]],
    "resource-group": lambda r, _: [["az", "group", "delete", "--name", r.name, "--yes"]],
}

HANDLERS: Dict[str, Dict[str, Handler]] = {"gcp": GCP, "aws": AWS, "azure": AZURE}
REVIEW_ONLY = {("gcp", "iam-binding")}

# Not deployment-owned, but billed while they exist — always listed after a teardown.
LEFTOVERS = {
    "gcp": ["Cloud Build source bucket gs://<project>_cloudbuild (if images were built remotely)",
            "Agent Runtime staging bucket (STAGING_BUCKET, default gs://<project>-agent-staging)",
            "Skill store bucket (SKILL_STORE, default gs://<project>-skills) (provisioned by you)",
            "Cloud Logging retention beyond the free allotment"],
    "aws": ["S3 skill store bucket (SKILLS_BUCKET) (provisioned by you)",
            "CloudWatch log groups of other stacks under /aws/bedrock-agentcore/",
            "The CloudFormation stack, if you deployed agentcore-platform.yaml by hand "
            "(aws cloudformation delete-stack --stack-name <name>)"],
    "azure": ["Skill store storage account (SKILLS_STORAGE_ACCOUNT) (provisioned by you)",
              "A pre-existing Foundry account the deploy reused (never deleted here); "
              "its model deployment is removed only if this deploy created it"],
}


def ledger_path(cloud: str) -> Path:
    return HERE / CLOUD_DIRS[cloud] / ".deployed" / "ledger.tsv"


def read_ledger(path: Path) -> List[Resource]:
    if not path.exists():
        return []
    seen, out = set(), []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        res = Resource.parse(line)
        key = (res.kind, res.name)
        if key in seen:  # re-deploys append again; keep the first creation
            continue
        seen.add(key)
        out.append(res)
    return out


def write_ledger(path: Path, resources: List[Resource]) -> None:
    if not resources:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(r.line() + "\n" for r in resources), encoding="utf-8")


def discover(cloud: str, runner: Runner, cfg: Dict[str, str]) -> List[Resource]:
    """Default-named resources for a deploy made without a ledger (creation order)."""
    found: List[Resource] = []
    if cloud == "gcp":
        project, region = cfg.get("PROJECT_ID", ""), cfg.get("REGION", "europe-west1")
        repo = cfg.get("REPO_NAME", "clinical-agents")
        if runner.capture(["gcloud", "artifacts", "repositories", "describe", repo, f"--location={region}",
                           f"--project={project}", "--format=value(name)"]).strip():
            found.append(Resource("artifact-repository", repo, {"location": region, "project": project}))
        if runner.capture(["gcloud", "secrets", "describe", "clinical-gemini-api-key", f"--project={project}",
                           "--format=value(name)"]).strip():
            found.append(Resource("secret", "clinical-gemini-api-key", {"project": project}))
        for svc in (cfg.get("AGENT_RESOURCE_NAME", "clinical-adk-agent"), "clinical-agent-harness"):
            if runner.capture(["gcloud", "run", "services", "describe", svc, f"--region={region}",
                               f"--project={project}", "--format=value(metadata.name)"]).strip():
                found.append(Resource("cloud-run-service", svc, {"region": region, "project": project}))
    elif cloud == "aws":
        region = cfg.get("AWS_REGION", "us-east-1")
        repo = cfg.get("ECR_REPO_NAME", "strands-clinical-agents")
        if runner.capture(["aws", "ecr", "describe-repositories", "--repository-names", repo, "--region", region]):
            found.append(Resource("ecr-repository", repo, {"region": region}))
        for name in (cfg.get("APP_RUNNER_NAME", "clinical-strands-agent"),):
            arn = runner.capture(["aws", "apprunner", "list-services", "--region", region, "--query",
                                  f"ServiceSummaryList[?ServiceName=='{name}'].ServiceArn", "--output", "text"]).strip()
            if arn and arn != "None":
                found.append(Resource("app-runner-service", arn, {"region": region}))
        ids = runner.capture(["aws", "bedrock-agentcore-control", "list-agent-runtimes", "--region", region, "--query",
                              f"agentRuntimes[?agentRuntimeName=='{cfg.get('AGENT_NAME', 'clinical_strands_agent')}']"
                              ".agentRuntimeId", "--output", "text"]).split()
        found += [Resource("agentcore-runtime", i, {"region": region}) for i in ids if i != "None"]
        mem = cfg.get("MEMORY_NAME", "clinical_agent_memory")
        ids = runner.capture(["aws", "bedrock-agentcore-control", "list-memories", "--region", region, "--query",
                              f"memories[?starts_with(id, '{mem}-')].id", "--output", "text"]).split()
        found += [Resource("agentcore-memory", i, {"region": region}) for i in ids if i != "None"]
    elif cloud == "azure":
        rg = cfg.get("RESOURCE_GROUP", "rg-clinical-agents")
        for app in (cfg.get("APP_NAME", "maf-clinical-agents"), "clinical-agent-harness"):
            if runner.capture(["az", "containerapp", "show", "--name", app, "--resource-group", rg, "--query", "name",
                               "-o", "tsv"]).strip():
                found.append(Resource("container-app", app, {"resource_group": rg}))
        # A ledger-less Azure teardown never deletes the resource group or a Foundry account: either may
        # pre-date the deploy. Use --delete-resource-group explicitly if the group is yours alone.
    return found


def plan_steps(cloud: str, resources: List[Resource], runner: Runner,
               include_review: bool = False) -> List[tuple]:
    handlers = HANDLERS[cloud]
    out = []
    for res in reversed(resources):  # newest first: dependents before what they depend on
        if res.kind not in handlers:
            raise KeyError(f"No teardown handler for {cloud} resource kind '{res.kind}'")
        if (cloud, res.kind) in REVIEW_ONLY and not include_review:
            out.append((res, None))
            continue
        out.append((res, handlers[res.kind](res, runner)))
    return out


def teardown(cloud: str, *, yes: bool = False, use_discover: bool = False, include_review: bool = False,
             delete_resource_group: Optional[str] = None, runner: Optional[Runner] = None,
             ledger: Optional[Path] = None, cfg: Optional[Dict[str, str]] = None) -> int:
    runner = runner or Runner()
    path = ledger or ledger_path(cloud)
    resources = read_ledger(path)
    source = f"ledger {path}"
    if not resources and use_discover:
        resources = discover(cloud, runner, cfg or {})
        source = "discovery of default resource names"
    if cloud == "azure" and delete_resource_group:
        resources = [r for r in resources if r.kind != "resource-group"] + [Resource("resource-group", delete_resource_group)]
        resources = [resources[-1]] + resources[:-1]  # the group goes last (it is first in creation order)
    print(f"Teardown plan for {cloud} from {source}:")
    if not resources:
        print("  nothing recorded. Run with --discover for a deploy made without a ledger.")
    steps = plan_steps(cloud, resources, runner, include_review)
    for res, cmds in steps:
        print(f"  - {res}" + ("  [review only: pass --include-iam to remove]" if cmds is None else ""))
    if not yes:
        print("\nPlan only. Re-run with --yes to delete.")
        _leftovers(cloud)
        return 0
    remaining = []
    for res, cmds in steps:
        if cmds is None:
            remaining.append(res)
            continue
        print(f"Deleting {res}...")
        if not all(runner.run(c) for c in cmds):
            print(f"  [!] failed; kept in the ledger for a retry: {res}")
            remaining.append(res)
    if path.exists() or remaining:
        write_ledger(path, list(reversed(remaining)))
    _leftovers(cloud)
    failed = [r for r in remaining if (cloud, r.kind) not in REVIEW_ONLY]
    print(f"\n{len(steps) - len(remaining)} resource(s) deleted, {len(failed)} failed.")
    return 1 if failed else 0


def _leftovers(cloud: str) -> None:
    print("\nCheck these too - not owned by the deployment, but billed while they exist:")
    for item in LEFTOVERS[cloud]:
        print(f"  - {item}")


def _load_config(cloud: str) -> Dict[str, str]:
    cfg: Dict[str, str] = {}
    path = HERE / CLOUD_DIRS[cloud] / "config.env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                key, value = line.split("=", 1)
                cfg[key.strip()] = value.strip().strip('"')
    import os
    cfg.update({k: v for k, v in os.environ.items() if k in {
        "PROJECT_ID", "REGION", "REPO_NAME", "AGENT_RESOURCE_NAME", "AWS_REGION", "ECR_REPO_NAME", "AGENT_NAME",
        "APP_RUNNER_NAME", "MEMORY_NAME", "RESOURCE_GROUP", "APP_NAME"}})
    return cfg


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cloud", choices=sorted(HANDLERS))
    parser.add_argument("--yes", "-y", action="store_true", help="delete (default: print the plan only)")
    parser.add_argument("--discover", action="store_true", help="no ledger: find default-named resources")
    parser.add_argument("--include-iam", action="store_true", help="also remove project IAM grants (GCP)")
    parser.add_argument("--delete-resource-group", metavar="NAME",
                        help="Azure: delete this whole resource group last (only if it holds nothing else of yours)")
    args = parser.parse_args(argv)
    return teardown(args.cloud, yes=args.yes, use_discover=args.discover, include_review=args.include_iam,
                    delete_resource_group=args.delete_resource_group, cfg=_load_config(args.cloud))


if __name__ == "__main__":
    sys.exit(main())

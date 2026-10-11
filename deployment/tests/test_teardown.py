"""
Teardown is part of every deployment: whatever a deploy script creates is
recorded, and destroy deletes exactly that, newest first, without touching
resources the deploy only reused. All tests run offline with a recording runner.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

DEPLOYMENT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("teardown", DEPLOYMENT / "teardown.py")
teardown = importlib.util.module_from_spec(spec)
sys.modules["teardown"] = teardown  # dataclasses resolve annotations through sys.modules
spec.loader.exec_module(teardown)
Resource = teardown.Resource

SCRIPTS = {"gcp": "gcloud-scripts", "aws": "aws-scripts", "azure": "az-scripts"}


class FakeRunner:
    def __init__(self, outputs=None, fail=()):
        self.outputs = outputs or {}
        self.fail = set(fail)
        self.ran = []

    def run(self, argv):
        self.ran.append(list(argv))
        return not any(f in " ".join(argv) for f in self.fail)

    def capture(self, argv):
        joined = " ".join(argv)
        return next((out for key, out in self.outputs.items() if key in joined), "")


def _ledger(tmp_path, resources):
    path = tmp_path / "ledger.tsv"
    teardown.write_ledger(path, resources)
    return path


AZURE_DEPLOY_ORDER = [
    Resource("resource-group", "rg-clinical-agents", {"location": "eastus"}),
    Resource("acr", "acrclinagents1", {"resource_group": "rg-clinical-agents"}),
    Resource("foundry-account", "ais-clinical-agents", {"resource_group": "rg-clinical-agents", "location": "eastus"}),
    Resource("foundry-project", "aiproj", {"account": "ais-clinical-agents", "resource_group": "rg-clinical-agents"}),
    Resource("foundry-model-deployment", "gpt-6.1-sol", {"account": "ais-clinical-agents", "resource_group": "rg-clinical-agents"}),
    Resource("log-analytics-workspace", "workspace-rg", {"resource_group": "rg-clinical-agents"}),
    Resource("containerapp-env", "cae-clinical-agents", {"resource_group": "rg-clinical-agents"}),
    Resource("container-app", "maf-clinical-agents", {"resource_group": "rg-clinical-agents"}),
    Resource("role-assignment", "/subscriptions/x/roleAssignments/y"),
]


def test_ledger_round_trip_and_redeploy_dedup(tmp_path):
    path = _ledger(tmp_path, AZURE_DEPLOY_ORDER)
    with path.open("a", encoding="utf-8") as fh:  # a re-deploy appends the same resource again
        fh.write(AZURE_DEPLOY_ORDER[1].line() + "\n")
    loaded = teardown.read_ledger(path)
    assert [(r.kind, r.name, r.attrs) for r in loaded] == [(r.kind, r.name, r.attrs) for r in AZURE_DEPLOY_ORDER]


def test_plan_deletes_newest_first_and_runs_nothing(tmp_path, capsys):
    path = _ledger(tmp_path, AZURE_DEPLOY_ORDER)
    runner = FakeRunner()
    assert teardown.teardown("azure", runner=runner, ledger=path) == 0
    assert runner.ran == []
    planned = [line.split()[1] for line in capsys.readouterr().out.splitlines() if line.startswith("  - ") and
               not line.startswith("  - Skill") and "(" not in line.split()[1]]
    kinds = [r.kind for r in reversed(AZURE_DEPLOY_ORDER)]
    assert planned[:len(kinds)] == kinds
    assert path.exists()


def test_delete_runs_in_dependency_order_and_purges_foundry(tmp_path):
    path = _ledger(tmp_path, AZURE_DEPLOY_ORDER)
    runner = FakeRunner()
    assert teardown.teardown("azure", yes=True, runner=runner, ledger=path) == 0
    verbs = [" ".join(c[:4]) for c in runner.ran]
    assert verbs[0].startswith("az role assignment delete")
    assert verbs[-1].startswith("az group delete")
    assert any("cognitiveservices account purge" in v for v in verbs)
    assert verbs.index("az containerapp delete --name") < verbs.index("az containerapp env delete")
    assert not path.exists()  # everything deleted: ledger removed


def test_failures_stay_in_the_ledger_for_a_retry(tmp_path):
    path = _ledger(tmp_path, AZURE_DEPLOY_ORDER)
    runner = FakeRunner(fail={"acr delete"})
    assert teardown.teardown("azure", yes=True, runner=runner, ledger=path) == 1
    assert [r.kind for r in teardown.read_ledger(path)] == ["acr"]


def test_aws_runtime_teardown_removes_its_log_groups_and_role_policies(tmp_path):
    path = _ledger(tmp_path, [
        Resource("ecr-repository", "strands-clinical-agents", {"region": "us-east-1"}),
        Resource("iam-role", "BedrockAgentCoreExecutionRole", {"region": "us-east-1"}),
        Resource("agentcore-memory", "clinical_agent_memory-abc", {"region": "us-east-1"}),
        Resource("agentcore-runtime", "clinical_strands_agent-xyz", {"region": "us-east-1"}),
    ])
    runner = FakeRunner(outputs={
        "describe-log-groups": '["/aws/bedrock-agentcore/runtimes/clinical_strands_agent-xyz-DEFAULT"]',
        "list-role-policies": '["ClinicalAgentRuntimeAccess", "AgentCoreFullAccess"]',
    })
    assert teardown.teardown("aws", yes=True, runner=runner, ledger=path) == 0
    flat = [" ".join(c) for c in runner.ran]
    assert flat[0].startswith("aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id clinical_strands_agent-xyz")
    assert any("delete-log-group --log-group-name /aws/bedrock-agentcore/runtimes/clinical_strands_agent-xyz-DEFAULT" in f
               for f in flat)
    assert sum("delete-role-policy" in f for f in flat) == 2
    assert flat[-1].startswith("aws ecr delete-repository --repository-name strands-clinical-agents --force")


def test_gcp_iam_grants_are_review_only_unless_requested(tmp_path):
    binding = Resource("iam-binding", "serviceAccount:1-compute@developer.gserviceaccount.com",
                       {"role": "roles/aiplatform.user", "project": "p"})
    service = Resource("cloud-run-service", "clinical-adk-agent", {"region": "europe-west1", "project": "p"})
    path = _ledger(tmp_path, [binding, service])
    runner = FakeRunner()
    assert teardown.teardown("gcp", yes=True, runner=runner, ledger=path) == 0
    assert all("remove-iam-policy-binding" not in " ".join(c) for c in runner.ran)
    assert [r.kind for r in teardown.read_ledger(path)] == ["iam-binding"]
    assert teardown.teardown("gcp", yes=True, include_review=True, runner=runner, ledger=path) == 0
    assert any("remove-iam-policy-binding" in " ".join(c) for c in runner.ran)


def test_unknown_kind_is_an_error_not_a_silent_skip(tmp_path):
    path = _ledger(tmp_path, [Resource("mystery-resource", "x")])
    with pytest.raises(KeyError, match="mystery-resource"):
        teardown.teardown("aws", runner=FakeRunner(), ledger=path)


# --------------------------------------------------------------------------- scripts ↔ teardown
SH_RECORD = re.compile(r"record_created\s+([a-z-]+)\s")
PS_RECORD = re.compile(r'Record-Created\s+"([a-z-]+)"')


def _kinds(cloud):
    folder = DEPLOYMENT / SCRIPTS[cloud]
    sh = set(SH_RECORD.findall((folder / "deploy.sh").read_text(encoding="utf-8")))
    ps = set(PS_RECORD.findall((folder / "deploy.ps1").read_text(encoding="utf-8")))
    return sh, ps


@pytest.mark.parametrize("cloud", sorted(SCRIPTS))
def test_every_recorded_kind_has_a_teardown_handler(cloud):
    sh, ps = _kinds(cloud)
    if cloud == "gcp":
        assert "agent-runtime\\t" in (DEPLOYMENT / "gcloud-scripts" / "agent_runtime.py").read_text(encoding="utf-8")
        sh, ps = sh | {"agent-runtime"}, ps | {"agent-runtime"}
    assert sh == ps, f"bash and PowerShell record different kinds: {sorted(sh ^ ps)}"
    assert sh <= set(teardown.HANDLERS[cloud]), sorted(sh - set(teardown.HANDLERS[cloud]))


CREATES = {  # create command (regex) -> kind it must record
    "gcp": {r"artifacts repositories create": "artifact-repository", r"secrets create": "secret",
            r"run deploy|\"run\", \"deploy\"": "cloud-run-service"},
    "aws": {r"ecr create-repository": "ecr-repository", r"iam create-role": "iam-role",
            r"create-memory": "agentcore-memory", r"create-agent-runtime": "agentcore-runtime",
            r"apprunner create-service": "app-runner-service"},
    "azure": {r"group create": "resource-group", r"acr create": "acr",
              r"cognitiveservices account create": "foundry-account", r"account project create": "foundry-project",
              r"account deployment create": "foundry-model-deployment", r"containerapp env create": "containerapp-env",
              r"containerapp create": "container-app", r"role assignment create": "role-assignment"},
}


@pytest.mark.parametrize("cloud", sorted(SCRIPTS))
@pytest.mark.parametrize("script", ["deploy.sh", "deploy.ps1"])
def test_every_create_in_a_deploy_script_is_recorded(cloud, script):
    text = (DEPLOYMENT / SCRIPTS[cloud] / script).read_text(encoding="utf-8")
    recorded = set((SH_RECORD if script.endswith(".sh") else PS_RECORD).findall(text))
    for pattern, kind in CREATES[cloud].items():
        if re.search(pattern, text):
            assert kind in recorded, f"{script} runs '{pattern}' but never records '{kind}'"


ESSENTIAL_STEPS = {
    "gcp": [r"builds submit|docker push", r"secrets create", r"run deploy|\"run\", \"deploy\"", r"ontogate build"],
    "aws": [r"docker push|buildx build.*--push", r"create-agent-runtime", r"ontogate build"],
    "azure": [r"acr build|docker push", r"containerapp create", r"ontogate build"],
}


@pytest.mark.parametrize("cloud", sorted(SCRIPTS))
@pytest.mark.parametrize("script", ["deploy.sh", "deploy.ps1"])
def test_deploy_scripts_keep_their_build_and_deploy_steps(cloud, script):
    text = (DEPLOYMENT / SCRIPTS[cloud] / script).read_text(encoding="utf-8")
    for step in ESSENTIAL_STEPS[cloud]:
        assert re.search(step, text), f"{script} lost the step matching '{step}'"


@pytest.mark.parametrize("cloud", sorted(SCRIPTS))
@pytest.mark.parametrize("script", ["destroy.sh", "destroy.ps1"])
def test_destroy_scripts_delegate_to_teardown(cloud, script):
    text = (DEPLOYMENT / SCRIPTS[cloud] / script).read_text(encoding="utf-8")
    assert "teardown.py" in text and f'"{cloud}"' in text or f" {cloud} " in text
    assert "\t" not in text


def test_aws_scripts_use_the_agentcore_control_plane_and_valid_names():
    for script in ("deploy.sh", "deploy.ps1"):
        text = (DEPLOYMENT / "aws-scripts" / script).read_text(encoding="utf-8")
        # Control-plane operations live in `bedrock-agentcore-control`; `bedrock-agentcore` is the data plane.
        assert not re.search(r"bedrock-agentcore (create|list|update|delete|get)-(agent-runtime|memory)", text), script
        for name in re.findall(r"(?:AGENT_NAME:-|MEMORY_NAME:-|\$AgentName\s+=\s+\"|\$MemoryName\s+=\s+\")([\w-]+)", text):
            assert re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,47}", name), f"{script}: invalid AgentCore name {name}"

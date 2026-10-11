"""
Live answer evals (plan P13.3): ask a deployed agent every applicable
competency question and grade its answer text with the deterministic graders.

    python evals/run.py --endpoint <service-url> [--token <bearer>] [--min-pass 0.95]

Run it per cloud (GCP / AWS / Azure) to compare grounding, clarification
precision and caveat compliance; role down-tiering (P13.5) and skill ablation
(P13.4) are decided from these reports. Needs a deployed service with live
models — the graders themselves are tested offline (evals/test_graders.py).
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "shared"), str(REPO / "conformance"), str(Path(__file__).resolve().parent)]

from graders import facts_for, grade  # noqa: E402
from live import _http_client, applicable_cases  # noqa: E402


def run(client: Any, label: str) -> Dict[str, Any]:
    from ontogate.release import current_release
    card = client.get("/.well-known/agent-card.json").json()
    params = card["capabilities"]["extensions"][0]["params"]
    rows: List[Dict[str, Any]] = []
    for case in applicable_cases(params.get("domains", [])):
        query = case["tc"]["input_text"]
        body = client.post("/api/v1/query", json={"prompt": query, "session_id": f"eval-{uuid.uuid4()}"}).json()
        answer = "\n".join(str(body.get(k) or "") for k in ("text", "clarification"))
        rows.append({"case": case["case"], "query": query, "checks": grade(answer, facts_for(query))})
    rates: Dict[str, float] = {}
    counts: Dict[str, List[bool]] = defaultdict(list)
    for row in rows:
        for check, value in row["checks"].items():
            if value is not None:
                counts[check].append(bool(value))
    for check, values in counts.items():
        rates[check] = sum(values) / len(values)
    release = current_release()
    return {"label": label, "served": params, "local_bundle_sha256": release.get("bundle_sha256"),
            "rates": rates, "answers": rows}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--token")
    parser.add_argument("--min-pass", type=float, default=None, help="fail if the overall pass rate is below this")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows consoles: never crash on ✓ or —
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    label = args.endpoint.split("//", 1)[-1].split("/", 1)[0]
    report = run(_http_client(args.endpoint, args.token), label)
    out = REPO / "dist" / "evals" / f"{label.replace(':', '_')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for check, rate in sorted(report["rates"].items()):
        print(f"{check:26} {rate:6.1%}")
    print(f"report: {out}")
    passed = report["rates"].get("passed", 0.0)
    return 1 if args.min_pass is not None and passed < args.min_pass else 0


if __name__ == "__main__":
    sys.exit(main())

"""
``ontogate`` command line.

    ontogate validate [pack] [--strict]     integrity rules (pack + scenario overlays)
    ontogate skills build|check|verify|role render, lint, lock and resolve runtime skills
    ontogate rdf export|validate [--owl-rl] SKOS/OWL/SHACL view of the loaded pack
    ontogate build [--no-owl-rl]            the full knowledge release (dist/release/)
    ontogate release verify                 fail closed unless the served release matches its pin
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional


def _rdf(argv: List[str]) -> int:
    from ontogate.config import get_default_registry, load_domain_config
    from ontogate.paths import domain_dir
    from ontogate import rdf_export
    from ontogate.roles import load_all_role_specs
    from ontogate.skills import load_lock, load_skills

    parser = argparse.ArgumentParser(prog="ontogate rdf")
    parser.add_argument("cmd", choices=["export", "validate"])
    parser.add_argument("--domain", help="domain pack id (default: the configured pack)")
    parser.add_argument("--owl-rl", action="store_true", help="materialise OWL 2 RL entailments")
    parser.add_argument("--formats", nargs="+", choices=sorted(rdf_export.FORMATS))
    args = parser.parse_args(argv)
    reg = load_domain_config(domain_dir(args.domain)) if args.domain else get_default_registry()
    roles, skills, lock = load_all_role_specs(), load_skills(), load_lock()
    if args.cmd == "validate":
        g = rdf_export.add_agent_graph(rdf_export.build_ontology_graph(reg), roles, skills, lock,
                                       domains=reg.domains)
        result = rdf_export.validate_shacl(g)
        for v in result["violations"]:
            print(f"{v['focus']}: {v['message']}")
        print("conforms" if result["conforms"] else f"{len(result['violations'])} violation(s)")
        return 0 if result["conforms"] else 1
    manifest = rdf_export.build_ontology_bundle(reg, owl_rl=args.owl_rl, formats=args.formats,
                                                roles=roles, skills=skills, lock=lock)
    print(json.dumps(manifest, indent=2))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "validate":
            from ontogate.validate import main as validate_main
            return validate_main(rest)
        if cmd == "skills":
            from ontogate.skills import main as skills_main
            return skills_main(rest)
        if cmd == "rdf":
            return _rdf(rest)
        if cmd == "build":
            from ontogate.release import build_release
            parser = argparse.ArgumentParser(prog="ontogate build")
            parser.add_argument("--no-owl-rl", action="store_true")
            args = parser.parse_args(rest)
            manifest = build_release(owl_rl=not args.no_owl_rl)
            print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, indent=2))
            print(f"{len(manifest['files'])} file(s) in the release")
            return 0
        if cmd == "release" and rest[:1] == ["verify"]:
            from ontogate.release import verify_release
            print(json.dumps(verify_release(), indent=2))
            return 0
    except (ValueError, ImportError, FileNotFoundError, RuntimeError) as exc:
        print(f"ontogate {cmd}: {exc}", file=sys.stderr)
        return 1
    print(f"Unknown command '{cmd}'.\n{__doc__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

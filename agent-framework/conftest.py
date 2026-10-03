"""
conftest.py — adds agent-framework and repo root to sys.path so that
'src.*' and 'google-adk-agents/src/core' are resolvable during tests.
"""
import sys
from pathlib import Path

# agent-framework dir (this file lives at its root)
_here = Path(__file__).resolve().parent          # agent-framework/
_repo = _here.parent                             # repo root

# Add agent-framework root first so 'src.*' resolves to agent-framework/src/
for p in (str(_here), str(_repo)):
    if p not in sys.path:
        sys.path.insert(0, p)

# 'src.core' lives in google-adk-agents — symlink-free approach: add it to path
# so 'from src.core.models import ...' resolves against google-adk-agents/src/core
_adk = _repo / "google-adk-agents"
if _adk.exists() and str(_adk) not in sys.path:
    sys.path.append(str(_adk))

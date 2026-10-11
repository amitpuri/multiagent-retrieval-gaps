"""
conftest.py — puts agent-framework (for ``src.*``) and the shared ``ontogate``
package on sys.path during tests.
"""
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent          # agent-framework/
_shared = _here.parent / "shared"                # shared/ (ontogate)

for p in (str(_here), str(_shared)):
    if p not in sys.path:
        sys.path.insert(0, p)

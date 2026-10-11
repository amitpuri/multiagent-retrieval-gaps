
import sys as _sys
from pathlib import Path as _Path


def _ensure_ontogate() -> None:
    """Make the shared ``ontogate`` package importable (installed wheel, else ``shared/`` in a checkout)."""
    try:
        import ontogate  # noqa: F401
    except ImportError:
        for parent in _Path(__file__).resolve().parents:
            if (parent / "shared" / "ontogate" / "__init__.py").is_file():
                _sys.path.insert(0, str(parent / "shared"))
                return
        raise


_ensure_ontogate()
# agent-framework src package

"""ProForma 2.0 interpretation string passthrough with optional validation."""

from __future__ import annotations

import warnings


def validate_interp(interp: str) -> bool:
    """Optionally validate a ProForma string using pyteomics if available.

    Returns True if valid (or if pyteomics is not installed).
    Emits a warning on parse failure but never raises.
    """
    try:
        from pyteomics import proforma as pf  # type: ignore[import]
        pf.parse(interp)
        return True
    except ImportError:
        return True
    except Exception as e:
        warnings.warn(f"ProForma parse warning for {interp!r}: {e}", UserWarning, stacklevel=3)
        return False

"""Coherent Quadrant scoring package — industry-aware Vendor Evaluation Matrix."""
from __future__ import annotations

from typing import Any


async def synthesize_quadrant(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from vendor_intel.quadrant.synthesize import synthesize_quadrant as _impl

    return await _impl(*args, **kwargs)


__all__ = ["synthesize_quadrant"]

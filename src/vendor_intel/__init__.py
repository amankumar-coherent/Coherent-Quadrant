"""Vendor intelligence pipeline — research-grade company lists."""

__version__ = "0.1.0"

# Every DeepSeek/OpenAI-compatible call made through this package should be
# tracked to output/cost_dashboard/deepseek_calls.jsonl with no gaps and no
# manual opt-in per call site. Installing the autotrack patch here, at
# package-import time, means it's live the moment anything does
# `import vendor_intel` — which every run_*.py / scripts/*.py entry point
# does — instead of depending on each script remembering to call it.
try:
    from vendor_intel.pipeline.deepseek_tracker import install_autotrack

    install_autotrack()
except Exception:
    pass

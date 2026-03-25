"""
Live test fixtures — provides the real switch_params, collects results
from each test, and writes testing/live.md after all live tests complete.

The --live flag and skip logic are in the parent testing/conftest.py.
"""
import datetime
from pathlib import Path

import pytest
import sys

# Ensure the project root is on sys.path (same as the parent conftest)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from arista import SWITCH_PARAMS


# ── Fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def switch_params():
    """Real device parameters imported from arista.py."""
    return SWITCH_PARAMS


@pytest.fixture(scope="session")
def live_results():
    """Shared list that live tests append their ConnectionResult objects to.
    The write_live_md fixture consumes this after all tests finish."""
    return []


@pytest.fixture(autouse=True, scope="session")
def write_live_md(live_results):
    """Session-scoped autouse fixture. Yields to let all tests run, then writes
    testing/live.md with a summary table and detailed output for each method."""
    yield

    if not live_results:
        return

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Live Test Results",
        f"*Generated: {timestamp}*",
        "",
        "## Summary",
        "",
        "| Method | Status | Time (s) |",
        "|--------|--------|----------|",
    ]

    passed = 0
    for r in live_results:
        status = "PASS" if r.success else "FAIL"
        if r.success:
            passed += 1
        lines.append(f"| {r.method} | {status} | {r.elapsed_seconds:.4f} |")

    lines.extend([
        "",
        f"**Passed: {passed}/{len(live_results)}**",
        "",
        "---",
        "",
        "## Detailed Output",
    ])

    for r in live_results:
        status = "PASS" if r.success else "FAIL"
        lines.append(f"\n### {r.method} — {status} ({r.elapsed_seconds:.4f}s)")

        if r.error:
            lines.append(f"\n**Error:** {r.error}")

        output = r.raw_output or "(no output)"
        # Truncate very long output to keep the report readable
        output_lines = output.splitlines()
        if len(output_lines) > 100:
            output = "\n".join(output_lines[:100]) + "\n... [truncated] ..."

        lines.extend(["", "```", output, "```"])

    lines.append("")

    # Write to testing/live.md (one level above the live/ directory)
    md_path = Path(__file__).resolve().parent.parent / "live.md"
    md_path.write_text("\n".join(lines))

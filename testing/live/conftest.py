"""Live test fixtures — real device params, result collection, and report generation."""
import datetime
from pathlib import Path

import pytest
from arista import SWITCH_PARAMS


@pytest.fixture(scope="session")
def switch_params():
    return SWITCH_PARAMS


@pytest.fixture(scope="session")
def live_results():
    return []


@pytest.fixture(autouse=True, scope="session")
def write_live_md(live_results):
    """After all live tests complete, write testing/live.md with results."""
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
        output_lines = output.splitlines()
        if len(output_lines) > 100:
            output = "\n".join(output_lines[:100]) + "\n... [truncated] ..."

        lines.extend(["", "```", output, "```"])

    lines.append("")

    md_path = Path(__file__).resolve().parent.parent / "live.md"
    md_path.write_text("\n".join(lines))

"""
Unit tests for arista.py helper functions, dataclass, and report generation.
All tests are pure logic — no network calls, no threads.
"""
import arista
from arista import ConnectionResult, _oc_ifaces_summary, _netconf_xml_summary, generate_report


# ── ConnectionResult dataclass ──────────────────────────────────


def test_connection_result_defaults():
    """Every connect_* function starts with ConnectionResult(method=...) and fills
    fields on success/failure. Verify the default contract is correct so a new
    ConnectionResult doesn't accidentally start with success=True or a non-empty error."""
    r = ConnectionResult(method="test")
    assert r.method == "test"
    assert r.success is False
    assert r.elapsed_seconds == 0.0
    assert r.data is None
    assert r.error is None
    assert r.raw_output == ""


# ── _oc_ifaces_summary ─────────────────────────────────────────


def test_oc_ifaces_summary_renders_table(sample_oc_ifaces):
    """RESTCONF, gNMI, and NETCONF all feed parsed OpenConfig data through this
    function. Verify it produces a readable ASCII table with headers and one row
    per interface."""
    output = _oc_ifaces_summary(sample_oc_ifaces)

    # Header row should contain column labels
    assert "Interface" in output
    assert "Admin" in output
    assert "Oper" in output

    # Each interface should appear as a row
    assert "Ethernet1" in output
    assert "Ethernet2" in output
    assert "Management0" in output

    # Status values from the fixture should be present
    assert "UP" in output
    assert "DOWN" in output


def test_oc_ifaces_summary_empty_list():
    """When a protocol returns no interfaces (e.g. empty RESTCONF response),
    the function should return a clear placeholder, not an empty string or crash."""
    assert _oc_ifaces_summary([]) == "(no interface data)"


def test_oc_ifaces_summary_missing_fields():
    """Interface dicts from different protocols may have missing keys. The function
    uses .get() chains with fallback values — verify it handles a bare-minimum dict
    without raising KeyError."""
    sparse = [{"name": "Loopback0"}]
    output = _oc_ifaces_summary(sparse)

    # Interface name should still appear
    assert "Loopback0" in output

    # Missing admin/oper fields should render as "?"
    assert "?" in output


# ── _netconf_xml_summary ───────────────────────────────────────


def test_netconf_xml_summary_valid_xml(sample_netconf_xml):
    """NETCONF returns XML. This function parses it using ElementTree and delegates
    to _oc_ifaces_summary. Verify the full pipeline: XML in → ASCII table out,
    with no raw XML leaking into the output."""
    output = _netconf_xml_summary(sample_netconf_xml)

    # Interface names from the XML fixture should appear in the table
    assert "Ethernet1" in output
    assert "Management0" in output

    # Should be a table, not raw XML
    assert "Interface" in output  # table header
    assert "<" not in output      # no XML tags in the rendered table


def test_netconf_xml_summary_malformed_xml():
    """NETCONF responses can be malformed or unexpected. The function catches parse
    errors and returns a readable error message instead of crashing the benchmark."""
    output = _netconf_xml_summary("<not-valid>>")
    assert output.startswith("(XML parse error:")


# ── generate_report ────────────────────────────────────────────


def test_generate_report_structure(sample_params, make_result):
    """The report is written to a file for the user to review. Verify it contains
    all expected sections: ranking table, summary stats, and per-method detail."""
    results = [
        make_result(method="FastMethod", success=True, elapsed_seconds=0.1, raw_output="fast data"),
        make_result(method="MidMethod", success=True, elapsed_seconds=0.5, raw_output="mid data"),
        make_result(method="BrokenMethod", success=False, elapsed_seconds=1.0, error="timeout"),
    ]
    report = generate_report(results, sample_params)

    # Major sections
    assert "PERFORMANCE RANKING" in report
    assert "SUMMARY" in report
    assert "DETAILED OUTPUT PER METHOD" in report

    # Target host from params
    assert sample_params["host"] in report

    # Ranking should show all methods
    assert "FastMethod" in report
    assert "MidMethod" in report
    assert "BrokenMethod" in report

    # Summary should identify fastest/slowest correctly
    assert "FastMethod" in report.split("Fastest")[1].split("\n")[0]
    assert "MidMethod" in report.split("Slowest")[1].split("\n")[0]

    # Failed method should show FAIL and error
    assert "FAIL" in report
    assert "timeout" in report


def test_generate_report_all_failed(sample_params, make_result):
    """When every connection fails, the SUMMARY section (which computes averages
    over successful results) should be skipped entirely — no division-by-zero,
    no misleading 'Fastest' line."""
    results = [
        make_result(method="A", success=False, elapsed_seconds=1.0, error="err1"),
        make_result(method="B", success=False, elapsed_seconds=2.0, error="err2"),
    ]
    report = generate_report(results, sample_params)

    assert "PERFORMANCE RANKING" in report
    # No summary stats when nothing succeeded
    assert "SUMMARY" not in report
    assert "Fastest" not in report

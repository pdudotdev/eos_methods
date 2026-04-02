"""Unit tests — pure logic, no network calls, no threads."""
from arista import ConnectionResult, _oc_ifaces_summary, _netconf_xml_summary, generate_report


def _result(**overrides):
    defaults = dict(method="TestMethod", success=True, elapsed_seconds=1.0,
                    data=None, error=None, raw_output="test output")
    defaults.update(overrides)
    return ConnectionResult(**defaults)


# ── _oc_ifaces_summary ────────────────────────────────────────

def test_oc_ifaces_summary_renders_table(sample_oc_ifaces):
    """Verify the core rendering function produces an ASCII table with headers and rows."""
    output = _oc_ifaces_summary(sample_oc_ifaces)

    assert "Interface" in output
    assert "Admin" in output
    assert "Oper" in output
    assert "Ethernet1" in output
    assert "Ethernet2" in output
    assert "Management0" in output
    assert "UP" in output
    assert "DOWN" in output


# ── _netconf_xml_summary ──────────────────────────────────────

def test_netconf_xml_summary_valid_xml(sample_netconf_xml):
    """XML in -> ASCII table out, no raw XML leaking through."""
    output = _netconf_xml_summary(sample_netconf_xml)

    assert "Ethernet1" in output
    assert "Management0" in output
    assert "Interface" in output
    assert "<" not in output


def test_netconf_xml_summary_malformed_xml():
    """Malformed XML returns an error message instead of crashing."""
    output = _netconf_xml_summary("<not-valid>>")
    assert output.startswith("(XML parse error:")
    assert "<not-valid>>" in output


def test_oc_ifaces_summary_empty_list():
    """Empty interface list returns a sentinel string, not a crash."""
    assert _oc_ifaces_summary([]) == "(no interface data)"


# ── generate_report ───────────────────────────────────────────

def test_generate_report_structure(sample_params):
    """Report contains all expected sections with correct ranking."""
    results = [
        _result(method="FastMethod", success=True, elapsed_seconds=0.1, raw_output="fast data"),
        _result(method="MidMethod", success=True, elapsed_seconds=0.5, raw_output="mid data"),
        _result(method="BrokenMethod", success=False, elapsed_seconds=1.0, error="timeout"),
    ]
    report = generate_report(results, sample_params)

    assert "PERFORMANCE RANKING" in report
    assert "SUMMARY" in report
    assert "DETAILED OUTPUT PER METHOD" in report
    assert sample_params["host"] in report
    assert "FastMethod" in report
    assert "BrokenMethod" in report
    assert "FastMethod" in report.split("Fastest")[1].split("\n")[0]
    assert "MidMethod" in report.split("Slowest")[1].split("\n")[0]
    assert "FAIL" in report
    assert "timeout" in report


def test_generate_report_all_failed(sample_params):
    """When every connection fails, SUMMARY is skipped (no division-by-zero)."""
    results = [
        _result(method="A", success=False, elapsed_seconds=1.0, error="err1"),
        _result(method="B", success=False, elapsed_seconds=2.0, error="err2"),
    ]
    report = generate_report(results, sample_params)

    assert "PERFORMANCE RANKING" in report
    assert "SUMMARY" not in report
    assert "Fastest" not in report

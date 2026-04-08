"""Integration tests for run_benchmark() — the ThreadPoolExecutor orchestrator.

All 7 connect_* functions are patched so no network is needed, but real threading runs.
"""
from unittest.mock import MagicMock

import pytest
import arista
from arista import ConnectionResult, run_benchmark


CONNECT_TARGETS = [
    "connect_ssh_cli",
    "connect_eapi",
    "connect_restconf",
    "connect_netconf",
    "connect_gnmi",
    "connect_snmpv3",
    "connect_telnet",
]


@pytest.fixture
def mock_connections(monkeypatch):
    """Patch all 7 connect_* functions on the arista module.
    Returns a dict {name: MagicMock} for per-test configuration."""
    mocks = {}
    for name in CONNECT_TARGETS:
        m = MagicMock(name=name)
        m.__name__ = name
        monkeypatch.setattr(arista, name, m)
        mocks[name] = m
    return mocks


def _result(method, elapsed):
    return ConnectionResult(method=method, success=True, elapsed_seconds=elapsed,
                            raw_output=f"{method} output")


def test_run_benchmark_collects_all_six(sample_params, mock_connections):
    """All 7 methods called, all results collected, sorted by time."""
    returns = [
        _result("SSH", 0.50), _result("eAPI", 0.10), _result("RESTCONF", 0.30),
        _result("NETCONF", 0.60), _result("gNMI", 0.20), _result("SNMPv3", 0.15),
        _result("Telnet", 0.40),
    ]
    for mock, ret in zip(mock_connections.values(), returns):
        mock.return_value = ret

    results = run_benchmark(sample_params)

    for mock in mock_connections.values():
        assert mock.call_count == 1
    assert len(results) == 7
    times = [r.elapsed_seconds for r in results]
    assert times == sorted(times)
    assert {r.method for r in results} == {"SSH", "eAPI", "RESTCONF", "NETCONF", "gNMI", "SNMPv3", "Telnet"}


def test_run_benchmark_handles_thread_exception(sample_params, mock_connections):
    """A raising connect_* is wrapped in ConnectionResult(success=False)."""
    good = [
        _result("SSH", 0.5), _result("eAPI", 0.1), _result("RESTCONF", 0.3),
        _result("NETCONF", 0.6), _result("SNMPv3", 0.15), _result("Telnet", 0.4),
    ]
    for name, ret in zip(list(mock_connections)[:4], good[:4]):
        mock_connections[name].return_value = ret
    mock_connections["connect_gnmi"].side_effect = RuntimeError("gRPC channel broken")
    mock_connections["connect_snmpv3"].return_value = good[4]
    mock_connections["connect_telnet"].return_value = good[5]

    results = run_benchmark(sample_params)

    assert len(results) == 7
    failures = [r for r in results if not r.success]
    assert len(failures) == 1
    assert "Thread error" in failures[0].error
    assert len([r for r in results if r.success]) == 6

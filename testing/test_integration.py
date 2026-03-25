"""
Integration tests for run_benchmark() — the ThreadPoolExecutor orchestrator.

All 6 connect_* functions are mocked so no network is needed, but the real
threading logic runs. This verifies that run_benchmark correctly submits all
methods, collects results, sorts by elapsed time, and handles thread errors.
"""
from unittest.mock import patch
from arista import ConnectionResult, run_benchmark


# The 6 connect_* functions that run_benchmark submits to the thread pool.
# Patches target the module-level names so the mocks are picked up when
# run_benchmark builds its methods list inside the function body.
CONNECT_FUNCTIONS = [
    "arista.connect_ssh_cli",
    "arista.connect_eapi",
    "arista.connect_restconf",
    "arista.connect_netconf",
    "arista.connect_gnmi",
    "arista.connect_telnet",
]


def _mock_result(method, elapsed):
    """Helper — returns a successful ConnectionResult with a given method name and time."""
    return ConnectionResult(
        method=method, success=True, elapsed_seconds=elapsed,
        raw_output=f"{method} output",
    )


def test_run_benchmark_collects_all_six(sample_params):
    """run_benchmark uses ThreadPoolExecutor to fire all 6 methods concurrently.
    Verify that: (1) all 6 are called exactly once, (2) all 6 results are collected,
    and (3) results come back sorted by elapsed_seconds ascending (fastest first)."""

    # Intentionally out-of-order times to test sorting
    mock_returns = [
        _mock_result("SSH", 0.50),
        _mock_result("eAPI", 0.10),
        _mock_result("RESTCONF", 0.30),
        _mock_result("NETCONF", 0.60),
        _mock_result("gNMI", 0.20),
        _mock_result("Telnet", 0.40),
    ]

    patches = {}
    for func_path, ret in zip(CONNECT_FUNCTIONS, mock_returns):
        patches[func_path] = patch(func_path, return_value=ret)

    # Apply all 6 patches. run_benchmark uses fn.__name__ to label futures,
    # so each mock needs a __name__ attribute matching the real function name.
    mocks = {}
    for name, p in patches.items():
        m = p.start()
        m.__name__ = name.split(".")[-1]  # e.g. "arista.connect_ssh_cli" → "connect_ssh_cli"
        mocks[name] = m
    try:
        results = run_benchmark(sample_params)
    finally:
        for p in patches.values():
            p.stop()

    # All 6 methods should be called exactly once
    for name, mock in mocks.items():
        assert mock.call_count == 1, f"{name} was not called exactly once"

    # All 6 results collected
    assert len(results) == 6

    # Results must be sorted by elapsed_seconds (ascending)
    times = [r.elapsed_seconds for r in results]
    assert times == sorted(times), f"Results not sorted: {times}"

    # All method names present
    methods = {r.method for r in results}
    assert methods == {"SSH", "eAPI", "RESTCONF", "NETCONF", "gNMI", "Telnet"}


def test_run_benchmark_handles_thread_exception(sample_params):
    """If a connect_* function raises an unhandled exception, the as_completed loop
    wraps it in a ConnectionResult(success=False, error='Thread error: ...') instead
    of losing the result. Verify we still get 6 results with the failure captured."""

    good_returns = [
        _mock_result("SSH", 0.5),
        _mock_result("eAPI", 0.1),
        _mock_result("RESTCONF", 0.3),
        _mock_result("NETCONF", 0.6),
        # gNMI will raise instead of returning
        _mock_result("Telnet", 0.4),
    ]

    patches = {}
    for func_path, ret in zip(CONNECT_FUNCTIONS[:4], good_returns[:4]):
        patches[func_path] = patch(func_path, return_value=ret)

    # gNMI raises a RuntimeError — simulates gRPC channel failure
    patches[CONNECT_FUNCTIONS[4]] = patch(
        CONNECT_FUNCTIONS[4], side_effect=RuntimeError("gRPC channel broken")
    )
    patches[CONNECT_FUNCTIONS[5]] = patch(
        CONNECT_FUNCTIONS[5], return_value=good_returns[4]
    )

    # Same __name__ fix as above — run_benchmark reads fn.__name__
    for name, p in patches.items():
        m = p.start()
        m.__name__ = name.split(".")[-1]
    try:
        results = run_benchmark(sample_params)
    finally:
        for p in patches.values():
            p.stop()

    # Still 6 results — the exception didn't reduce the count
    assert len(results) == 6

    # Exactly one result should be the captured thread error
    failures = [r for r in results if not r.success]
    assert len(failures) == 1
    assert "Thread error" in failures[0].error

    # The other 5 should be successful
    successes = [r for r in results if r.success]
    assert len(successes) == 5

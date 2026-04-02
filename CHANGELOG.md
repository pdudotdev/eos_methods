# Changelog

## v1.0.0

Initial release — 7-method concurrent benchmark for Arista EOS.

- Benchmark SSH/CLI, eAPI, RESTCONF, NETCONF, gNMI, SNMPv3, and Telnet simultaneously
- Concurrent execution via `ThreadPoolExecutor` with per-method timing
- Auto-generated performance report ranked fastest to slowest
- `benchmark_runner.py` for multi-run averaging (default 100 runs)
- Wireshark packet captures for all 7 protocols in `pcaps/`
- TLS session key export via `SSLKEYLOGFILE` for eAPI/RESTCONF decryption
- Live test suite (`pytest --live`) against a real Arista device
- Unit and integration tests with mocked connections
- EOS setup guide with all required switch configuration (`eos_setup/`)
- Detailed technical report (`REPORT.md`) with per-protocol wire-level analysis

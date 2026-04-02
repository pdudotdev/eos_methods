# Changelog

## v1.2.0

Mutual TLS (mTLS) for eAPI, RESTCONF, and gNMI.

- CA-based certificate architecture: one CA signs all server and client certs
- Client certificate authentication for eAPI, RESTCONF (`requests` `cert=` param) and gNMI (`pygnmi` `path_cert`/`path_key`/`path_root`)
- EOS SSL profiles updated with `trust certificate benchmark-ca.crt` for client cert verification
- `SWITCH_PARAMS` uses `ca_cert` for server verification (replaces per-protocol cert pinning), `client_cert`/`client_key` for mTLS
- Certificate generation and EOS import steps documented in `eos_setup/commands.txt`
- mTLS architecture and Wireshark visibility documented in `REPORT.md`
- TACACS+ and RADIUS configuration documentation added to `eos_setup/commands.txt` (EOS config, Ubuntu server setup, lockout prevention)
- Fixed live test checks for abbreviated interface names (`Et`/`Ma` vs `Ethernet`/`Management`)

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

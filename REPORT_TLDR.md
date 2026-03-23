# Arista EOS Management Interface Benchmark — TL;DR

Six methods, same query (`show interfaces status`), same device, same LAN. Times measured end-to-end by the Python benchmark script (`arista.py`) and confirmed at the packet level via Wireshark captures.

## Final Rankings

| Rank | Method                | Time      | Packets |
|------|-----------------------|-----------|---------|
| 1    | eAPI (HTTPS JSON-RPC) | ~97ms     | 19      |
| 2    | RESTCONF (HTTPS REST) | ~110ms    | 25      |
| 3    | gNMI (gRPC/HTTP2/TLS) | ~234ms    | 41      |
| 4    | SSH/CLI (Netmiko)     | ~1,967ms  | 80      |
| 5    | NETCONF (ncclient)    | ~2,240ms  | 1,130   |
| 6    | Telnet/CLI (Netmiko)  | ~6,444ms  | 95      |

## What Makes Each Method Fast or Slow

**1. eAPI — ~97ms** — TCP handshake → TLS 1.3 (1-RTT) → one HTTP POST → response. No model translation: EOS runs the CLI command natively and serialises directly to compact JSON (2.4KB, gzip-compressed to 385 bytes on the wire). Server processing: 32ms. The remaining ~53ms is Python SSL context initialisation — a fixed client-side cost paid equally by RESTCONF.

**2. RESTCONF — ~110ms** — Identical TLS + HTTP/1.1 stack as eAPI. The extra ~13ms comes entirely from server-side OpenConfig YANG model translation: EOS must traverse the schema and map native interface state field-by-field into standards-compliant JSON. Response is 10× larger (23KB vs 2.4KB) due to YANG namespace annotations and container nesting.

**3. gNMI — ~234ms** — HTTP/2 over TLS adds a mandatory SETTINGS round-trip before any RPC can proceed. Same OpenConfig YANG translation as RESTCONF, but output is wrapped in protobuf gNMI envelopes (`json_ietf` encoding), inflating the response to 41KB. Client spends ~73ms decoding protobuf post-receipt. With persistent channels (no reconnect per poll), the HTTP/2 setup and TLS cost amortise to near-zero — gNMI becomes the highest-throughput method for sustained telemetry collection.

**4. SSH/CLI — ~1,967ms** — SSH banner exchange (~27ms) + ECDH key exchange (~47ms), then password authentication: the EOS SSH server takes ~1.47s to verify credentials regardless of auth method (key-based auth was tested — same delay on this platform). After auth, Netmiko spends ~200ms preparing the shell (disabling paging, detecting prompts) before the command is sent. Actual data transfer: 784 bytes in ~150ms. The session overhead is everything.

**5. NETCONF — ~2,240ms** — SSH transport on port 830, so pays the full SSH handshake and the same ~1.47s password auth penalty. Added on top: mandatory capability `<hello>` exchange before any RPC can proceed, and a 156KB XML response (66× eAPI's size) spanning 845 TCP segments. XML verbosity is the defining cost: every field needs an opening tag, closing tag, and namespace declaration. With subtree filters, base:1.1 framing, and persistent sessions, this is practical — without them, it is not.

**6. Telnet — ~6,444ms** — No TLS means less transport work, yet Telnet is 3× slower than SSH. The reason is Netmiko's Telnet backend uses fixed `time.sleep()` delays (~3.9s total) while waiting for IAC option negotiation — a limitation with no event-driven alternative in Netmiko. Credentials and all output are transmitted in plaintext. Not a viable option under any circumstances in production.

## Key Takeaways

- **eAPI** is the right default for Arista-specific operational polling: fastest, lowest overhead, simplest.
- **RESTCONF / gNMI** trade ~15–140ms for vendor-neutral OpenConfig data. Use when multi-vendor tooling or sustained telemetry matters; prefer gNMI for continuous collection (persistent channels eliminate per-poll setup cost).
- **SSH/CLI** is unavoidable for tasks with no API equivalent. The ~1.47s auth delay dominates — keep sessions alive where possible.
- **NETCONF** requires subtree filters, chunked framing (base:1.1), and persistent sessions to be practical at scale.
- **Telnet** has no valid production use case — performance and security both disqualify it.

---

## Lab Context

> **These results are specific to an Arista cEOS 4.35.0F lab running in containerlab, with the client and device on the same local subnet (sub-millisecond RTT).** Rankings and absolute times may differ in other environments, including:
> - **Physical EOS hardware** — may have different CPU characteristics and supports `encoding="proto"` for gNMI, which would significantly reduce gNMI's response size and likely move it above RESTCONF in the ranking.
> - **Production environments** — TACACS+/RADIUS authentication adds network round-trip time to every SSH/NETCONF connection on top of the ~1.47s local auth delay measured here.
> - **WAN or high-latency links** — API methods (eAPI, RESTCONF, gNMI) benefit most from fewer round trips; SSH/NETCONF and Telnet are disproportionately penalised.
> - **Other EOS versions or vendors** — YANG model translation costs, SSH auth processing, and Telnet IAC handling vary across implementations.
> - **Different query scope** — a targeted subtree filter or a smaller interface table will compress all times; a full operational state dump will expand them.

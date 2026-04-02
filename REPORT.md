# Arista EOS Management Interface Testing

Seven methods, same query (`show interfaces status`), same device, same LAN. Times measured end-to-end by the Python benchmark script (`arista.py`) and confirmed at the packet level via Wireshark captures.

## Final Rankings

| Rank | Method                | Time      | Packets |
|------|-----------------------|-----------|---------|
| 1    | eAPI (HTTPS JSON-RPC) | ~70ms     | 19      |
| 2    | RESTCONF (HTTPS REST) | ~123ms    | 25      |
| 3    | gNMI (gRPC/HTTP2/TLS) | ~228ms    | 41      |
| 4    | SNMPv3 (pysnmp/USM)   | ~434ms    | 15      |
| 5    | SSH/CLI (Netmiko)     | ~1,908ms  | 80      |
| 6    | NETCONF (ncclient)    | ~2,724ms  | 1,130   |
| 7    | Telnet/CLI (Netmiko)  | ~6,415ms  | 95      |

## What Makes Each Method Fast or Slow

**1. eAPI — ~70ms** — TCP handshake → TLS 1.3 (1-RTT) → one HTTP POST → response. No model translation: EOS runs the CLI command natively and serialises directly to compact JSON (2.4KB, gzip-compressed to 385 bytes on the wire). Server processing: 32ms. The remaining ~53ms is Python SSL context initialisation — a fixed client-side cost paid equally by RESTCONF.

**2. RESTCONF — ~123ms** — Identical TLS + HTTP/1.1 stack as eAPI. The extra ~13ms comes entirely from server-side OpenConfig YANG model translation: EOS must traverse the schema and map native interface state field-by-field into standards-compliant JSON. Response is 10× larger (23KB vs 2.4KB) due to YANG namespace annotations and container nesting.

**3. gNMI — ~228ms** — HTTP/2 over TLS adds a mandatory SETTINGS round-trip before any RPC can proceed. Same OpenConfig YANG translation as RESTCONF, but output is wrapped in protobuf gNMI envelopes (`json_ietf` encoding), inflating the response to 41KB. Client spends ~73ms decoding protobuf post-receipt. With persistent channels (no reconnect per poll), the HTTP/2 setup and TLS cost amortise to near-zero — gNMI becomes the highest-throughput method for sustained telemetry collection.

**4. SNMPv3 — ~434ms** — UDP transport eliminates TCP handshake and TLS entirely. 15 packets total across 6 request-response pairs over ~108ms of wire time. The first exchange is mandatory USM engine discovery: an unauthenticated probe (msgFlags 0x04) to learn the agent's engine ID (`f5717f...`), boot counter, and clock — required before the client can compute authentication and privacy keys. The remaining 5 pairs are authenticated+encrypted GetBulk walks (msgFlags 0x07) across three IF-MIB::ifTable columns (ifDescr, ifAdminStatus, ifOperStatus). Per-pair latency averages ~2.8ms after discovery. Requests are ~165 bytes; responses average ~1,461 bytes. The username ("benchmark") and engine ID are visible in cleartext USM headers; only the PDU payload is AES-128-encrypted. The ~326ms gap between wire time and Python-measured time is pysnmp overhead: async event loop startup, USM key localisation, and BER decoding of 5 bulk response PDUs. Fewest packets of any method — no TLS certificates, no YANG model, no schema validation.

**5. SSH/CLI — ~1,908ms** — SSH banner exchange (~27ms) + ECDH key exchange (~47ms), then password authentication: the EOS SSH server takes ~1.47s to verify credentials regardless of auth method (key-based auth was tested — same delay on this platform). After auth, Netmiko spends ~200ms preparing the shell (disabling paging, detecting prompts) before the command is sent. Actual data transfer: 784 bytes in ~150ms. The session overhead is everything.

**6. NETCONF — ~2,724ms** — SSH transport on port 830, so pays the full SSH handshake and the same ~1.47s password auth penalty. Added on top: mandatory capability `<hello>` exchange before any RPC can proceed, and a 156KB XML response (66× eAPI's size) spanning 845 TCP segments. XML verbosity is the defining cost: every field needs an opening tag, closing tag, and namespace declaration. With subtree filters, base:1.1 framing, and persistent sessions, this is practical — without them, it is not.

**7. Telnet — ~6,415ms** — No TLS means less transport work, yet Telnet is 3× slower than SSH. The reason is Netmiko's Telnet backend uses fixed `time.sleep()` delays (~3.9s total) while waiting for IAC option negotiation — a limitation with no event-driven alternative in Netmiko. Credentials and all output are transmitted in plaintext. Not a viable option under any circumstances in production.

## Key Takeaways

- **eAPI** is the right default for Arista-specific operational polling: fastest, lowest overhead, simplest.
- **RESTCONF / gNMI** trade ~15–140ms for vendor-neutral OpenConfig data. Use when multi-vendor tooling or sustained telemetry matters; prefer gNMI for continuous collection (persistent channels eliminate per-poll setup cost).
- **SSH/CLI** is unavoidable for tasks with no API equivalent. The ~1.47s auth delay dominates — keep sessions alive where possible.
- **NETCONF** requires subtree filters, chunked framing (base:1.1), and persistent sessions to be practical at scale.
- **SNMPv3** ranked 4th at ~434ms — fast on the wire (~108ms, 15 packets) but penalised by pysnmp async overhead (~326ms). UDP + USM (SHA auth + AES-128 priv) means no TLS and no TCP — fewest packets of any method. USM discovery round-trip is mandatory per session. Lightweight for polling counters (IF-MIB); no YANG model, no structured config. Certificate-based SNMP (TSM, RFC 6353) is not available on EOS. Being replaced by gNMI for telemetry in modern networks.
- **Telnet** has no valid production use case — performance and security both disqualify it.

---

## Lab Context

> **These results are specific to an Arista cEOS 4.35.0F lab running in containerlab, with the client and device on the same local subnet (sub-millisecond RTT).** Rankings and absolute times may differ in other environments, including:
> - **Physical EOS hardware** — may have different CPU characteristics and supports `encoding="proto"` for gNMI, which would significantly reduce gNMI's response size and likely move it above RESTCONF in the ranking.
> - **Production environments** — TACACS+/RADIUS authentication adds network round-trip time to every SSH/NETCONF connection on top of the ~1.47s local auth delay measured here.
> - **WAN or high-latency links** — API methods (eAPI, RESTCONF, gNMI) benefit most from fewer round trips; SSH/NETCONF and Telnet are disproportionately penalised.
> - **Other EOS versions or vendors** — YANG model translation costs, SSH auth processing, and Telnet IAC handling vary across implementations.
> - **Different query scope** — a targeted subtree filter or a smaller interface table will compress all times; a full operational state dump will expand them.

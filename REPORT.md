# Arista EOS Management Tests

- **Device:** Arista EOS · 172.20.20.208<br/>
- **Query:** 
`show interfaces status` / `openconfig-interfaces:interfaces`<br/>
- **Captured:** Wireshark with `SSLKEYLOGFILE` for TLS decryption · local subnet<br/>
- **Client libraries:** `requests` (eAPI, RESTCONF) · `pygnmi` (gNMI) · `netmiko` (SSH/CLI, Telnet) · `ncclient` (NETCONF)

---

## Introduction

This report presents a packet-level analysis of all six management interfaces available on Arista EOS: eAPI, RESTCONF, gNMI, SSH/CLI, NETCONF, and Telnet. Each method was used to retrieve the same data — the full interface status table — from a single switch, with Wireshark captures taken simultaneously on the local subnet.

The goal is not to benchmark raw throughput. The goal is to understand *why* each method takes the time it does: which phases dominate, what the protocol overhead looks like on the wire, how server-side processing costs differ, and where each method's design trade-offs show up in packet timing.

Every measurement reported here is derived directly from the packet captures — inter-packet gaps, segment sizes, and cumulative elapsed time from SYN to the final packet. No estimates. Where encryption hides payload contents, only sizes and timing are reported; where traffic is in plaintext or decryptable (Telnet, SSH banners and key exchange, eAPI/RESTCONF with the included TLS key log), the exact content is shown.

### Test Environment

The device under test ran Arista EOS with all six management interfaces enabled simultaneously:

| Interface | Port  | Enabled via                              |
|-----------|-------|------------------------------------------|
| eAPI      | 443   | `management api http-commands`           |
| RESTCONF  | 6020  | `management api restconf` + SSL profile  |
| gNMI      | 6030  | `management api gnmi` + SSL profile      |
| NETCONF   | 830   | `management api netconf`                 |
| SSH/CLI   | 22    | `management ssh`                         |
| Telnet    | 23    | `management telnet`                      |

All six connections were initiated concurrently from a Python benchmark script on the same local subnet as the device. TLS key material for eAPI and RESTCONF was captured via `SSLKEYLOGFILE`; the session keys for these two captures are included in this repository as `pcaps/tls_keys.log` and can be loaded into Wireshark to decrypt the HTTP content. gNMI uses `grpcio`/BoringSSL, which does not write to `SSLKEYLOGFILE`, so gNMI payload content is not visible in the capture; SSH traffic is encrypted after the key exchange phase; Telnet is fully plaintext.

### Benchmark Results Summary

Measured end-to-end time from TCP SYN to final packet (Python client on same LAN as device):

| Rank | Method                  | Total Time | Packets | Port |
|------|-------------------------|------------|---------|------|
| 1    | eAPI (HTTPS JSON-RPC)   | ~97ms      | 19      | 443  |
| 2    | RESTCONF (HTTPS REST)   | ~110ms     | 25      | 6020 |
| 3    | gNMI (gRPC/HTTP2/TLS)   | ~234ms     | 41      | 6030 |
| 4    | SSH/CLI (Netmiko)       | ~1,967ms   | 80      | 22   |
| 5    | NETCONF (ncclient)      | ~2,240ms   | 1,130   | 830  |
| 6    | Telnet/CLI (Netmiko)    | ~6,444ms   | 95      | 23   |

The spread between fastest and slowest is **6.35 seconds** — for retrieving identical data from the same device. The analysis that follows explains exactly where that time goes.

> **Packet size methodology:** All byte values in packet diagrams correspond to Wireshark's **Length** column — the full Ethernet frame including all headers (14-byte Ethernet + 20-byte IP + 20-32-byte TCP + payload). Body text that refers to "response payload" or "content size" describes application-layer data only.

---

## 1. eAPI — HTTPS JSON-RPC

**Port:** 443 | **Protocol:** HTTP/1.1 over TLS 1.3 | **Total packets:** 19 | **Measured time:** ~97ms

> **Wireshark note:** To view the decrypted HTTP request and response content, load `pcaps/tls_keys.log` via **Edit → Preferences → Protocols → TLS → (Pre)-Master-Secret log filename**. The HTTP payload in phases 4 and 6 will then be visible.

### Phase 1 — TCP 3-Way Handshake (~0.05ms)

```
#1   Client  →  Server   [SYN]     seq=2356749439, win=64240, MSS=1460, SACK, WScale=10
#2   Server  →  Client   [SYN-ACK] seq=2117539484, ack=2356749440, win=65160
#3   Client  →  Server   [ACK]
```

Standard TCP connection establishment. Both sides advertise:
- **MSS 1460** — maximum segment size for this link
- **SACK** — selective acknowledgement, allows retransmitting only lost segments
- **Window scaling** — allows receive windows larger than 64KB

This completes in under a millisecond since both endpoints are on the same local subnet.

### Phase 2 — Python/requests SSL Setup (~53ms gap)

After the TCP ACK there is a **52.8ms pause** before the TLS ClientHello. No packets are exchanged. This is pure client-side overhead: Python's `requests` library initialising the SSL context, building the HTTP session object, and preparing the request. This cost is paid regardless of what the server does.

### Phase 3 — TLS 1.3 Handshake (~4ms, packets 4–10)

```
#4   Client  →  Server   [TLS ClientHello]          583 bytes
#5   Server  →  Client   [ACK]
#6   Server  →  Client   [TLS ServerHello+...]       1374 bytes
#7   Client  →  Server   [ACK]
#8   Client  →  Server   [TLS Client Finished]       146 bytes
#9   Server  →  Client   [Application Data]          145 bytes  ← NewSessionTicket
#10  Server  →  Client   [Application Data]          145 bytes  ← NewSessionTicket
```

**ClientHello (583 bytes):** The client advertises supported cipher suites, TLS extensions, and critically a **key share** — its EC Diffie-Hellman public key. This enables TLS 1.3's 1-RTT handshake: the server can derive shared keys immediately without waiting for another round trip.

**ServerHello + EncryptedExtensions + Certificate + Finished (1374 bytes):** In TLS 1.3, the server compresses what was previously 4–5 separate messages into a single flight. It sends its own DH public key (completing the key agreement), its certificate (already encrypted — unlike TLS 1.2), and its Finished message. Both sides now have all the keys needed for application data.

**Client Finished (146 bytes):** The client confirms the handshake is complete. Application data can now flow.

**Two NewSessionTicket messages (145 bytes each):** TLS 1.3 session tickets, sent after the handshake, allow session resumption in future connections (0-RTT), avoiding the full key exchange cost. Not used in this benchmark since each run creates a fresh connection.

The entire TLS handshake takes **~4ms** — significantly faster than TLS 1.2, which required 2 round trips for key exchange alone.

### Phase 4 — HTTP POST Request (~0.3ms, packets 11–13)

```
#11  Client  →  Server   [Application Data]  336 bytes
#12  Client  →  Server   [Application Data]  231 bytes
#13  Server  →  Client   [ACK]
```

The eAPI request is sent as an **HTTP POST to a single fixed endpoint** (`/command-api`). The request is split at the natural headers/body boundary across two TCP segments — packet 11 carries the HTTP headers, packet 12 carries the JSON body:

```
POST /command-api HTTP/1.1
Host: 172.20.20.208
User-Agent: python-requests/2.32.5
Accept-Encoding: gzip, deflate
Accept: */*
Connection: keep-alive
Content-Length: 143
Content-Type: application/json
Authorization: Basic YWRtaW46YWRtaW4=

{"jsonrpc": "2.0", "method": "runCmds", "params": {"version": 1, "cmds": ["show interfaces status"], "format": "json"}, "id": "benchmark-eapi"}
```

There is no URL hierarchy, no YANG path, no resource model — just a CLI command string wrapped in a JSON-RPC envelope. The server needs no model translation; it runs the command as-is. Authentication is HTTP Basic Auth (`Authorization: Basic YWRtaW46YWRtaW4=` = `admin:admin` in Base64), transmitted inside the TLS tunnel. The `Accept-Encoding: gzip` header tells the server to compress the response.

### Phase 5 — Server Processing (~32ms gap)

After the ACK on the request, the server goes silent for **31.96ms**. This is the Arista EOS command processor running `show interfaces status` internally and serialising the result directly into its native JSON structure. No YANG model mapping, no schema validation — the data comes straight out of the EOS data plane.

### Phase 6 — HTTP Response (~6.8ms, packets 14–16)

```
#14  Server  →  Client   [Application Data]  961 bytes
#15  Server  →  Client   [Application Data]  108 bytes  ← HTTP response tail
#16  Client  →  Server   [ACK]
```

**Total HTTP response: 893 bytes** across two TLS records (487 bytes of headers + 402 bytes of chunked body). The body is gzip-compressed: 385 bytes of compressed data that decompresses to a **2,373-byte JSON** object — Arista's native flat representation of interface state, directly serialised with no namespace annotations or YANG container nesting.

The 108-byte second packet contains the second (10-byte) gzip chunk — the deflate end-of-block marker, CRC32, and ISIZE — plus the chunked transfer terminator (`\r\n0\r\n\r\n`). The server closes the connection without sending a TLS `close_notify` alert; it signals end-of-response via the chunked terminator and then closes with a TCP FIN. Decryption of both records is possible using `pcaps/tls_keys.log`.

### Phase 7 — TCP Teardown (~0.8ms, packets 17–19)

```
#17  Client  →  Server   [FIN+ACK]
#18  Server  →  Client   [FIN+ACK]
#19  Client  →  Server   [ACK]
```

Clean 4-way FIN (compressed into 3 steps since the server piggybacks its FIN). Connection is fully closed.

### Timing Breakdown

| Phase                         | Packets  | Duration   |
|-------------------------------|----------|------------|
| TCP handshake                 | #1–3     | ~0.05ms    |
| Python SSL context setup      | —        | ~52.8ms    |
| TLS 1.3 handshake             | #4–10    | ~4.3ms     |
| HTTP request transmission     | #11–13   | ~0.3ms     |
| Server processing             | —        | ~32ms      |
| HTTP response                 | #14–16   | ~6.8ms     |
| TCP teardown                  | #17–19   | ~0.8ms     |
| **Total**                     |          | **~97ms**  |

### Why eAPI Is Fastest

The **32ms server processing time** and **compact response** are the key metrics. eAPI avoids all model translation — no YANG schema traversal, no namespace mapping, no OpenConfig conversion. The EOS command processor returns its native data structure, serialises it directly to JSON (2,373 bytes), and gzip-compresses it to 385 bytes on the wire. The wire payload is minimal, server work is minimal, and the HTTP/1.1 framing adds no overhead beyond what TLS already costs.

The 52.8ms Python setup cost is a fixed overhead paid by all HTTPS-based methods equally and is not a property of eAPI itself.

---

## 2. RESTCONF — HTTPS REST

**Port:** 6020 | **Protocol:** HTTP/1.1 over TLS 1.3 | **Total packets:** 25 | **Measured time:** ~110ms

> **Wireshark note:** Wireshark misidentifies port 6020 as X11 (which uses the 6000–6063 range). To see decrypted HTTP traffic: load `pcaps/tls_keys.log` (see eAPI note above), then right-click any packet → **Decode As → TLS**. The HTTP payload will then be visible.

### Phase 1 — TCP 3-Way Handshake (~0.04ms)

```
#1   Client  →  Server   [SYN]     port 33928 → 6020
#2   Server  →  Client   [SYN-ACK]
#3   Client  →  Server   [ACK]
```

Identical mechanics to eAPI. Completes in under a millisecond on the local subnet. The only difference is the destination port (6020 instead of 443), which routes to the RESTCONF server process rather than the eAPI server.

### Phase 2 — Python/requests SSL Setup (~45ms gap)

A **44.7ms pause** after the TCP ACK before the TLS ClientHello. Same cause as eAPI: Python's `requests` library initialising the SSL context and HTTP session. Slightly shorter than eAPI's 52.8ms gap because all six connections are launched concurrently — the SSL context may already be partially warm from the eAPI connection starting at the same time.

### Phase 3 — TLS 1.3 Handshake (~5ms, packets 4–10)

```
#4   Client  →  Server   [TLS ClientHello]     583 bytes
#5   Server  →  Client   [ACK]
#6   Server  →  Client   [TLS ServerHello+...] 1494 bytes
#7   Client  →  Server   [ACK]
#8   Client  →  Server   [TLS Finished]        130 bytes
#9   Client  →  Server   [HTTP GET request]    387 bytes
#10  Server  →  Client   [ACK]
```

The ServerHello is slightly larger than eAPI's (1494 vs 1374 bytes) because this connection uses the **`restconf` SSL profile** with its own self-signed certificate (`restconf.crt`). The certificate itself — embedded in the TLS ServerHello flight — carries the additional bytes.

One notable difference: after sending the TLS Finished, the client **immediately** sends the HTTP GET request in the next packet (387 bytes) without waiting. TLS 1.3 allows this — application data can be sent as soon as the client has finished its part of the handshake, before the server even acknowledges it. This reduces one round trip compared to TLS 1.2 behaviour.

### Phase 4 — HTTP GET Request (~1ms)

```
#9   Client  →  Server   [Application Data]  387 bytes
```

Unlike eAPI's POST to a single endpoint, RESTCONF uses a **GET to a YANG-defined URL**:

```
GET /restconf/data/openconfig-interfaces:interfaces HTTP/1.1
Host: 172.20.20.208:6020
Accept: application/yang-data+json
```

The URL path directly mirrors the YANG model hierarchy. `openconfig-interfaces:interfaces` is the module-qualified path to the root of the OpenConfig interfaces tree. There is no request body — the resource being read is fully expressed in the URL itself.

### Phase 5 — Server Processing (~56ms gap)

After acknowledging the request, the server goes silent for **56.3ms** — nearly double eAPI's 32ms processing time. This is the YANG model translation cost: EOS must take its native internal interface state and map it field-by-field through the OpenConfig `interfaces` YANG schema, building a standards-compliant JSON structure with correct namespaces, container hierarchies, and augment nodes. This work happens entirely on the device CPU before the first byte of response is sent.

The ~24ms difference vs eAPI's server processing time is a direct measurement of the OpenConfig model translation overhead.

### Phase 6 — HTTP Response (~1ms, packets 11–22)

```
#11  Server  →  Client   [Application Data]  1274 bytes
#12  Server  →  Client   [Application Data]  2460 bytes
#13  Client  →  Server   [ACK]
#14  Server  →  Client   [Application Data]  626 bytes
#15  Server  →  Client   [Application Data]  4832 bytes
#16  Client  →  Server   [ACK]
#17  Server  →  Client   [Application Data]  6018 bytes
#18  Server  →  Client   [Application Data]  7204 bytes
#19  Client  →  Server   [ACK]
#20  Server  →  Client   [Application Data]  1228 bytes
#21  Server  →  Client   [Application Data]  95 bytes   ← TLS close_notify
#22  Client  →  Server   [ACK]
```

**Total response payload: ~23,209 bytes** — approximately **~10× larger** than eAPI's 2,373-byte JSON for the same interface data.

The size difference is structural. The YANG-mapped JSON is deeply nested with full namespace annotations, parent containers (`config`, `state`, `subinterfaces`), and Arista augment nodes for every field. Where eAPI returns `"linkStatus": "connected"`, RESTCONF returns the same information wrapped in multiple container levels with explicit YANG namespace attributes.

The response spans **8 TCP segments** (7 data + 1 TLS close_notify), ACK'd in groups as the TCP receive window fills and drains. All data arrives in a rapid burst — the server serialises the full response before sending, and TCP handles segmentation automatically.

### Phase 7 — Connection Close

```
#23  Client  →  Server   [FIN+ACK]
#24  Server  →  Client   [Application Data]  90 bytes   ← TLS close_notify
#25  Client  →  Server   [RST]
```

The client sends FIN, the server responds with a TLS `close_notify` alert, and the client resets rather than completing a clean 4-way FIN. This is a common pattern with Python's `requests` — the underlying connection is torn down by the OS before the server's FIN is processed.

### Timing Breakdown

| Phase                              | Packets  | Duration   |
|------------------------------------|----------|------------|
| TCP handshake                      | #1–3     | ~0.04ms    |
| Python SSL context setup           | —        | ~44.7ms    |
| TLS 1.3 handshake                  | #4–10    | ~5ms       |
| HTTP GET request                   | #9       | ~1ms       |
| Server processing (YANG translation)| —       | ~56ms      |
| HTTP response (23KB, 8 segments)   | #11–22   | ~1ms       |
| Connection close                   | #23–25   | ~1ms       |
| **Total**                          |          | **~110ms** |

### Why RESTCONF Is Slower Than eAPI

Two compounding factors:

1. **Server processing:** 56ms vs 32ms — the YANG model translation adds ~24ms of CPU work on the device for every request.
2. **Response size:** 23KB vs 2,373 bytes — the YANG-compliant JSON is ~10× larger, requiring 8 TCP segments vs eAPI's 2.

The TLS handshake cost is essentially identical between the two methods. The difference is entirely in what the server has to do to produce the response and how much data it sends back.

---

## 3. gNMI — gRPC over HTTP/2 over TLS 1.3

**Port:** 6030 | **Protocol:** gRPC over HTTP/2 over TLS 1.3 | **Total packets:** 41 | **Measured time:** ~234ms

> **TLS decryption note:** `grpcio` uses **BoringSSL** — Google's fork of OpenSSL — which does not write to `SSLKEYLOGFILE`. The TLS keys for this connection are not in `tls_keys.log`. To see plaintext gNMI traffic, temporarily switch the device back to insecure gNMI (no SSL profile) and recapture.

> **Certificate note:** The device's gNMI TLS certificate is pinned locally as `pcaps/gnmi.crt` and passed to pygnmi via `path_cert`. This eliminates the certificate-retrieval TCP session that pygnmi would otherwise open before the real gRPC channel — a saving of ~36ms per call. To re-export the certificate from the device (e.g. after a cert rotation):
> ```bash
> # Fetch the certificate presented on the gNMI port and save as PEM
> openssl s_client -connect 172.20.20.208:6030 </dev/null 2>/dev/null \
>     | openssl x509 -outform PEM > pcaps/gnmi.crt
>
> # Verify the CN and SAN match the device IP
> openssl x509 -in pcaps/gnmi.crt -noout -subject -ext subjectAltName
> ```

### Phase 1 — TCP 3-Way Handshake (~0.05ms, packets 1–3)

```
#1   Client  →  Server   74 bytes   [SYN]
#2   Server  →  Client   74 bytes   [SYN-ACK]
#3   Client  →  Server   66 bytes   [ACK]
```

### Phase 2 — TLS 1.3 Handshake (~19ms, packets 4–15)

```
#4   Client  →  Server   316 bytes  TLS ClientHello           +4ms (pygnmi credential setup)
#5   Server  →  Client   [ACK]
#6   Server  →  Client   1530 bytes TLS ServerHello+Cert+...  +6.7ms
#7   Client  →  Server   [ACK]
#8   Client  →  Server   130 bytes  TLS key exchange material
#9   Client  →  Server   170 bytes  TLS
#10  Client  →  Server   170 bytes  TLS Certificate + Finished
#11  Server  →  Client   [ACK]
#12  Server  →  Client   78 bytes   TLS NewSessionTicket
#13  Server  →  Client   109 bytes  TLS
#14  Server  →  Client   97 bytes   TLS
#15  Client  →  Server   97 bytes   TLS Finished
```

The 4ms gap before the ClientHello (packet #4) is pygnmi setting up `grpc.ssl_channel_credentials()` using the locally-pinned certificate — zero TCP connections required. The ServerHello flight (packet #6, 1530 bytes) carries the device certificate, server extensions, and server Finished in a single TLS record burst. The server sends a NewSessionTicket (packet #12) for potential future session resumption.

### Phase 3 — HTTP/2 + gRPC Setup (~0.8ms, packets 16–19)

This is the layer that fundamentally separates gNMI from eAPI and RESTCONF. HTTP/2 requires a connection negotiation round-trip before any gNMI data can be requested:

```
#16  Client  →  Server   384 bytes  HTTP/2 SETTINGS + gRPC HEADERS + DATA
                                    └─ HEADERS: gRPC method, path (/gnmi.gNMI/Get)
                                    └─ DATA: protobuf-encoded gNMI GetRequest for /interfaces
#17  Server  →  Client   [ACK]
#18  Server  →  Client   118 bytes  HTTP/2 SETTINGS (server side)
#19  Client  →  Server   105 bytes  HTTP/2 SETTINGS ACK
```

The client combines its HTTP/2 SETTINGS, gRPC HEADERS, and the gNMI GetRequest DATA into a single 384-byte packet (#16). The **HTTP/2 SETTINGS exchange** (packets #16–#19) is mandatory — both endpoints negotiate stream parameters (max concurrent streams, flow control window sizes, max frame size) before any RPC proceeds. This requires one full round trip that HTTP/1.1 methods (eAPI, RESTCONF) simply don't pay.

The gRPC request is a **protobuf-encoded gNMI GetRequest** for path `/interfaces` inside an HTTP/2 DATA frame, with `encoding=JSON_IETF` specified in the request.

### Phase 4 — Server Processing (~73ms, packet 20)

```
#20  Server  →  Client   [ACK only]   ← 41ms gap then 32ms until burst 1
```

A single ACK-only packet during the ~73ms the device spends translating EOS native interface state through the OpenConfig YANG model and encoding the result into protobuf gNMI Notification/Update structures with JSON_IETF-encoded YANG values — the deepest model translation stack of all six methods.

### Phase 5 — gNMI Response — Two Bursts (packets 21–36)

```
── Burst 1 (~17KB, ~0.5ms) ──
#21  Server  →  Client   4832 bytes
#22  Client  →  Server   [ACK]
#23  Server  →  Client   6018 bytes
#24  Server  →  Client   6801 bytes
#25  Client  →  Server   [ACK]
#26  Client  →  Server   105 bytes  HTTP/2 WINDOW_UPDATE
#27  Server  →  Client   [ACK]
#28  Server  →  Client   105 bytes  HTTP/2 WINDOW_UPDATE
── HTTP/2 flow control + 2nd-half server encoding (~28ms) ──
#29  Client  →  Server   218 bytes  HTTP/2 WINDOW_UPDATE
#30  Server  →  Client   118 bytes
#31  Client  →  Server   105 bytes  HTTP/2 WINDOW_UPDATE ACK
── Burst 2 (~24KB, ~0.2ms) ──
#32  Server  →  Client   10762 bytes
#33  Client  →  Server   [ACK]
#34  Server  →  Client   11948 bytes
#35  Server  →  Client   1449 bytes
#36  Client  →  Server   [ACK]
```

**Total response payload: ~41,414 bytes** — the largest payload of all six methods in raw bytes, though NETCONF's XML exceeds it in total wire size.

The size is explained by the encoding: `encoding="json_ietf"` causes the device to return namespace-qualified JSON-encoded OpenConfig data **nested inside** protobuf gNMI Notification/Update wrapper structures. The YANG model data is as verbose as RESTCONF's (23KB) and the protobuf framing adds overhead on top. `encoding="proto"` would replace all field names with compact integer tags and substantially reduce the response — but this cEOS version supports only `json`, `json_ietf`, and `ascii`; proto encoding is available on physical EOS hardware platforms.

**WINDOW_UPDATE frames** (packets #26, #28, #29, #31) carry no application data — they are HTTP/2's flow control mechanism, signalling how much additional data the receiver can accept. The ~28ms between bursts reflects the server encoding the second half of the response after sending the first.

### Phase 6 — Connection Teardown (packets 37–41)

```
#37  Client  →  Server   105 bytes  HTTP/2 GOAWAY frame       ← ~73ms after burst 2
#38  Server  →  Client   105 bytes  HTTP/2 GOAWAY response
#39  Client  →  Server   [ACK]
#40  Server  →  Client   90 bytes   TLS close_notify
#41  Client  →  Server   [RST]
```

The ~73ms gap before packet #37 is pygnmi decoding 41KB of JSON-in-protobuf into Python data structures after receiving the full response. gRPC uses HTTP/2's **GOAWAY frame** (packets #37–#38) for graceful stream shutdown before the TCP FIN — an explicit protocol-level close sequence absent in HTTP/1.1 methods.

### Timing Breakdown

| Phase                                              | Packets   | Duration    |
|----------------------------------------------------|-----------|-------------|
| TCP handshake                                      | #1–3      | ~0.05ms     |
| pygnmi credential setup (pre-ClientHello)          | —         | ~4ms        |
| TLS 1.3 handshake                                  | #4–15     | ~15ms       |
| HTTP/2 + gRPC setup (SETTINGS, HEADERS)            | #16–19    | ~0.8ms      |
| Server processing (YANG translation + encoding)    | #20       | ~73ms       |
| gNMI response burst 1 (17KB)                       | #21–28    | ~0.5ms      |
| HTTP/2 flow control + server 2nd-half encoding     | #29–31    | ~28ms       |
| gNMI response burst 2 (24KB)                       | #32–36    | ~0.2ms      |
| pygnmi protobuf decode                             | —         | ~73ms       |
| HTTP/2 GOAWAY + TCP teardown                       | #37–41    | ~27ms       |
| **Total**                                          |           | **~234ms**  |

### Why gNMI Has More Overhead Than RESTCONF

Despite both performing the same YANG model translation:

1. **HTTP/2 SETTINGS negotiation** (packets #16–19): Mandatory round trip before any RPC can proceed — absent in HTTP/1.1.
2. **Larger response** (packets #21–35): 41KB vs 23KB due to `json_ietf`-in-protobuf encoding. `encoding="proto"` would reduce this significantly on supported platforms — this cEOS version supports only `json`, `json_ietf`, and `ascii`.
3. **Deeper server-side encoding:** YANG translation + protobuf wrapping adds overhead vs RESTCONF's pure YANG-to-JSON translation.
4. **Client-side decode cost:** pygnmi spends ~73ms decoding the 41KB protobuf response before issuing GOAWAY — this overhead does not appear in eAPI or RESTCONF where the application layer (JSON) is parsed incrementally.

⚠️ With persistent channels (gNMI supports long-lived streaming — no reconnect per query), items 1 and 4 amortise across thousands of polls. On physical EOS hardware (and other platforms that support `encoding="proto"`), item 2 drops further — compact protobuf field tags replace verbose JSON key strings. For continuous telemetry collection at scale, gNMI is typically the highest-throughput method.

*Sources: [pygnmi client.py](https://github.com/akarneliuk/pygnmi/blob/master/pygnmi/client.py) · [pygnmi GitHub](https://github.com/akarneliuk/pygnmi)*

---

## 4. SSH/CLI — Netmiko (SSHv2/paramiko)

**Port:** 22 | **Protocol:** SSHv2 (paramiko) | **Total packets:** 80 | **Measured time:** ~1,967ms

> **Wireshark note:** SSH session keys are derived in-memory during the key exchange and are never exported — there is no `SSLKEYLOGFILE` equivalent for SSH. All traffic after the NEWKEYS message (packet #12) is permanently opaque in the capture. Only sizes and timing are available for the encrypted phases.

### Phase 1 — TCP 3-Way Handshake (~0.05ms, packets 1–3)

```
#1   Client  →  Server   [SYN]     port 58692 → 22
#2   Server  →  Client   [SYN-ACK]
#3   Client  →  Server   [ACK]
```

Standard TCP handshake. Completes in ~0.05ms on the local subnet. Unlike TLS-based methods, no SSL context setup gap follows — SSH begins its own protocol exchange immediately after the TCP ACK.

### Phase 2 — SSH Version Banner Exchange (~27ms, packets 4–7)

```
#4   Client  →  Server   90 bytes   "SSH-2.0-paramiko_4.0.0\r\n"
#5   Server  →  Client   [ACK]
#6   Server  →  Client   87 bytes   "SSH-2.0-OpenSSH_9.9\r\n"
#7   Client  →  Server   [ACK]
```

Both sides identify themselves immediately after TCP connect. This is the SSH protocol version string, sent in plaintext before any encryption is established. It is clearly visible in Wireshark as readable text. The client announces `paramiko_4.0.0` (the Python SSH library used by Netmiko), and the server responds with `OpenSSH_9.9` (Arista EOS's SSH server).

The ~27ms gap between packets 4 and 6 is the server preparing its key exchange data.

### Phase 3 — SSH Key Exchange (~47ms, packets 8–13)

```
#8   Client  →  Server   1322 bytes   SSH2_MSG_KEXINIT (algorithm lists)
#9   Server  →  Client   802 bytes    SSH2_MSG_KEXINIT (algorithm lists)
#10  Client  →  Server   114 bytes    SSH2_MSG_KEX_ECDH_INIT (client public key)
#11  Server  →  Client   578 bytes    SSH2_MSG_KEX_ECDH_REPLY (server public key + host key + signature)
#12  Client  →  Server   82 bytes     SSH2_MSG_NEWKEYS
#13  Server  →  Client   [ACK]        — 41ms gap, then encryption begins
```

**KEXINIT (packets 8–9, 1322 + 802 bytes):** Both sides send their full list of supported algorithms — key exchange methods, host key types, ciphers, MACs, and compression. The negotiation result (the intersection of both lists) determines what crypto is used for the session. These packets are still in plaintext and are readable in Wireshark.

**ECDH exchange (packets 10–11):** The client sends its ephemeral Elliptic Curve Diffie-Hellman public key (114 bytes). The server responds with its own ECDH public key, its host key (used to authenticate the server's identity), and a signature proving it holds the private key (578 bytes total). Both sides can now independently derive the same shared secret — this is the key agreement.

**NEWKEYS (packet 12, 82 bytes):** The smallest but most important message — signals that both sides are switching to the negotiated encryption. Every packet after this is encrypted with the derived keys. This is the equivalent of TLS's Change Cipher Spec.

The 41ms ACK-only gap at packet 13 is the server processing the key exchange and computing the session keys before the encrypted phase begins.

### Phase 4 — Encrypted Authentication (~1,540ms, packets 14–25)

```
#14  Client  →  Server   130 bytes   SSH_MSG_SERVICE_REQUEST (encrypted)
#15  Server  →  Client   [ACK]
#16  Server  →  Client   130 bytes   SSH_MSG_SERVICE_ACCEPT (encrypted)
#17  Client  →  Server   162 bytes   SSH_MSG_USERAUTH_REQUEST - username (encrypted)
#18  Server  →  Client   146 bytes   SSH_MSG_USERAUTH_FAILURE or methods (encrypted)
#19  Client  →  Server   130 bytes   (encrypted)
#20  Server  →  Client   130 bytes   (encrypted)
#21  Client  →  Server   178 bytes   SSH_MSG_USERAUTH_REQUEST - password (encrypted)
#22  Server  →  Client   146 bytes   (encrypted)
#23  Client  →  Server   130 bytes   (encrypted)
#24  Server  →  Client   [ACK]       — 42ms gap
     ← 1.476s gap — server authenticating password →
#25  Server  →  Client   130 bytes   SSH_MSG_USERAUTH_SUCCESS (encrypted)
```

All packets in this phase are fully encrypted — only sizes and timing are visible in the capture. The notable pattern is that all SSH encrypted packets appear at frame lengths of 130, 146, 162, or 178 bytes. The SSH payload portion (frame length minus 66 bytes of Ethernet + IP + TCP headers) is always a multiple of **64 bytes**. This is SSH's mandatory packet padding: all encrypted SSH packets must be padded to a multiple of the cipher's block size (16 bytes for AES), and the minimum size is 16 bytes — Netmiko/paramiko adds extra padding to fixed 64-byte SSH payload blocks.

The **1.476s gap** between packets 24 and 25 is the single largest delay in the entire SSH exchange. This is the server authenticating the password: hashing it, comparing against stored credentials, and performing any PAM/AAA checks. SSH password authentication is inherently sequential — the server must verify before sending USERAUTH_SUCCESS, and the client cannot send anything until it receives that confirmation.

This single step accounts for **~75% of the total connection time**.

### Phase 5 — Channel Setup (~197ms, packets 26–45)

```
#26  Client  →  Server   114 bytes   SSH_MSG_CHANNEL_OPEN (encrypted)
#27  Server  →  Client   [ACK]
#28  Server  →  Client   114 bytes   SSH_MSG_CHANNEL_OPEN_CONFIRM (encrypted)
#29  Client  →  Server   146 bytes   SSH_MSG_CHANNEL_REQUEST - shell/pty (encrypted)
#30  Server  →  Client   658 bytes   (encrypted — session banner + prompt data)
#31  Client  →  Server   [ACK]       — 41ms gap
     ... many 130-byte encrypted packets — Netmiko prompt detection,
         disable paging, find enable mode, prepare shell ...
#46  Client  →  Server   146 bytes   SSH_MSG_CHANNEL_DATA — command (encrypted)
```

After authentication, SSH opens a **channel** — a logical stream within the SSH connection. SSH supports multiple concurrent channels, though Netmiko only uses one. The channel open/confirm (packets 26–28) establishes it, and the channel request (packet 29) asks for a shell or exec environment.

The 658-byte server response (packet 30) contains the EOS login banner and the device prompt, all encrypted. Netmiko must detect the prompt pattern in the decrypted payload to know the shell is ready.

The subsequent ~40 packets of small 130–146-byte exchanges (64–80-byte SSH payloads) are Netmiko's session preparation: disabling terminal paging (`terminal length 0`), confirming the prompt, and navigating to the right privilege level. Each prompt/response round trip requires a full packet exchange. This preparation phase has no equivalent in API-based methods.

### Phase 6 — Command Execution and Response (~153ms, packets 46–80)

```
#46  Client  →  Server   146 bytes   "show interfaces status" (encrypted)
     ... packets 47–70: prompt echo + small encrypted exchanges ...
#71  Server  →  Client   850 bytes   command output (encrypted)
#72  Server  →  Client   130 bytes   (encrypted — trailing prompt)
#73  Client  →  Server   [ACK]
     ... packets 74–79: Netmiko reads until prompt detected, sends disconnect ...
#80  Client  →  Server   [RST]
```

The actual command (`show interfaces status`) is sent as a single encrypted packet (packet 46, 146 bytes). The response arrives as two packets: the 850-byte packet (#71) containing the interface table, followed by the device prompt confirming the command completed.

**Total response payload: ~784 bytes** — CLI text output, substantially smaller than eAPI's 2,373-byte JSON for the same interface data. The CLI format has no field names, no nesting, and no structure overhead — just an ASCII table. But unlike eAPI where the client knows the response is complete when HTTP returns 200 OK, Netmiko must detect the **prompt string** at the end of the output to know the command has finished. This requires reading and parsing each incoming packet, adding latency.

### Timing Breakdown

| Phase                                | Packets  | Duration                              |
|--------------------------------------|----------|---------------------------------------|
| TCP handshake                        | #1–3     | ~0.05ms                               |
| SSH banner exchange                  | #4–7     | ~27ms                                 |
| SSH key exchange                     | #8–13    | ~47ms                                 |
| Encrypted authentication             | #14–25   | ~1,540ms (incl. 1,476ms password auth gap) |
| Channel setup + Netmiko prep         | #26–45   | ~197ms                                |
| Command + response                   | #46–80   | ~153ms                                |
| **Total**                            |          | **~1,967ms**                          |

### Why SSH Is Slow

Three compounding factors:

1. **Password authentication (1.476s):** Sequential server-side credential verification with no parallelism possible. This is inherent to SSH password auth — see the key-auth note below for why switching to key-based auth provides no measurable improvement on this platform.
2. **Netmiko session preparation:** Disabling paging, detecting prompts, and preparing the shell adds hundreds of milliseconds of prompt-wait cycles with no equivalent in API methods.
3. **Prompt-based response detection:** Unlike HTTP which has a `Content-Length` header to know when data is complete, SSH/CLI relies on detecting the device prompt — requiring pattern matching on each received packet.

The actual data transfer (784 bytes, ~0.1ms) is trivially fast. The cost is entirely in the session establishment and interaction model.

### Key-Based Auth — Lab Result

Key-based authentication was tested against this device (ed25519 key, `username admin ssh-key` configured). The measured time was **~1,932ms** — virtually identical to password auth (~1,967ms). Packet capture confirmed why: after the client sends its signed public key auth request, there is a **~1,473ms gap** before EOS responds with auth success. This gap is the same duration as the password-auth delay, and with no TACACS+/RADIUS servers configured (pure local auth), it is EOS's own SSH authentication processing overhead applied uniformly regardless of auth method. Key auth eliminates the password exchange round trip but not this server-side delay.

On real EOS hardware or different EOS versions this behaviour may differ. For this cEOS lab platform, key auth provides no measurable timing benefit.

---

## 5. NETCONF — ncclient (SSH Subsystem, RFC 6242)

**Port:** 830 | **Protocol:** NETCONF over SSH (RFC 6242) | **Total packets:** 1,130 | **Measured time:** ~2,240ms

> **Wireshark note:** Same as SSH/CLI — SSH session keys are not exportable. All traffic after NEWKEYS (packet #15) is permanently opaque. The NETCONF XML content described in phases 5–8 is derived from ncclient library behaviour and EOS documentation, not from decrypting the capture.

### Overview: NETCONF Runs Inside SSH

NETCONF is not an independent protocol on the wire — RFC 6242 mandates that it runs as an SSH subsystem. Port 830 is the dedicated IANA port for this, but the transport is identical SSH: the same TCP connection, the same key exchange, the same encrypted channels. This means the full SSH handshake and password authentication cost is paid before a single NETCONF byte is exchanged.

The 1,130 packets in this capture break down roughly as: ~40 packets for SSH setup · ~5 packets for NETCONF session setup · ~1,080 packets for the XML response · ~5 packets for teardown.

### Phase 1 — TCP 3-Way Handshake (~0.07ms, packets 1–3)

```
#1   Client  →  Server   [SYN]     port 50382 → 830
#2   Server  →  Client   [SYN-ACK]
#3   Client  →  Server   [ACK]
```

Standard TCP handshake to port 830. Mechanically identical to the SSH/CLI handshake on port 22, completing in under a millisecond on the local subnet.

### Phase 2 — SSH Version Banner Exchange (~28ms, packets 4–7)

```
#4   Client  →  Server   90 bytes   "SSH-2.0-paramiko_4.0.0\r\n"
#5   Server  →  Client   [ACK]
#6   Server  →  Client   87 bytes   "SSH-2.0-OpenSSH_9.9\r\n"
#7   Client  →  Server   [ACK]
```

Same plaintext banner exchange as SSH/CLI. The client identifies as `paramiko_4.0.0` — ncclient uses paramiko as its SSH backend, the same library Netmiko uses. The 27ms gap between packets 4 and 6 is the server preparing its key exchange data.

### Phase 3 — SSH Key Exchange (~90ms, packets 8–16)

```
#8   Server  →  Client   802 bytes    SSH2_MSG_KEXINIT (server algorithm lists)
#9   Client  →  Server   [ACK]
#10  Client  →  Server   1322 bytes   SSH2_MSG_KEXINIT (client algorithm lists)
#11  Server  →  Client   [ACK]       — 41ms gap, server computing ECDH parameters
#12  Client  →  Server   114 bytes   SSH2_MSG_KEX_ECDH_INIT (client public key)
#13  Server  →  Client   [ACK]
#14  Server  →  Client   578 bytes   SSH2_MSG_KEX_ECDH_REPLY (server key + signature)
#15  Client  →  Server   82 bytes    SSH2_MSG_NEWKEYS
#16  Server  →  Client   [ACK]       — 41ms gap, server computing session keys
```

In this capture the server sends its KEXINIT first (packet 8). Both sides send their KEXINIT as soon as they've processed the peer's version string — the ordering depends on which side sends faster. The exchange is otherwise identical to SSH/CLI: KEXINIT algorithm negotiation, ECDH key agreement, NEWKEYS signalling the switch to encrypted transport.

The two 41ms ACK-only gaps — one before the ECDH init and one after NEWKEYS — are the server performing the elliptic curve computations.

### Phase 4 — Encrypted Authentication (~1,530ms, packets 17–28)

```
#17  Client  →  Server   130 bytes   SSH_MSG_SERVICE_REQUEST (encrypted)
#18  Server  →  Client   [ACK]
#19  Server  →  Client   130 bytes   SSH_MSG_SERVICE_ACCEPT (encrypted)
#20  Client  →  Server   162 bytes   SSH_MSG_USERAUTH_REQUEST - username (encrypted)
#21  Server  →  Client   146 bytes   SSH_MSG_USERAUTH_FAILURE / methods (encrypted)
#22  Client  →  Server   130 bytes   (encrypted)
#23  Server  →  Client   130 bytes   (encrypted)
#24  Client  →  Server   178 bytes   SSH_MSG_USERAUTH_REQUEST - password (encrypted)
#25  Server  →  Client   146 bytes   (encrypted)
#26  Client  →  Server   130 bytes   (encrypted)
#27  Server  →  Client   [ACK]       — 41ms gap
     ← 1,474ms gap — server verifying password →
#28  Server  →  Client   130 bytes   SSH_MSG_USERAUTH_SUCCESS (encrypted)
```

Fully encrypted — contents not visible, only sizes and timing. The pattern mirrors the SSH/CLI capture exactly: all encrypted SSH packets at 130–178-byte frame lengths (64-byte-multiple SSH payloads), followed by the same **1,474ms gap** for server-side password verification.

This single step — password hashing and PAM/AAA checking — accounts for **~65% of the total connection time**. It is identical in both SSH/CLI and NETCONF because the transport layer is the same.

### Phase 5 — SSH Channel + NETCONF Hello Exchange (~52ms, packets 29–39)

```
#29  Client  →  Server   114 bytes   SSH_MSG_CHANNEL_OPEN (encrypted)
#30  Server  →  Client   [ACK]
#31  Server  →  Client   114 bytes   SSH_MSG_CHANNEL_OPEN_CONFIRM (encrypted)
#32  Client  →  Server   146 bytes   SSH_MSG_CHANNEL_REQUEST — subsystem=netconf (encrypted)
#33  Server  →  Client   658 bytes   NETCONF server <hello> (encrypted)
#34  Client  →  Server   [ACK]       — 41ms gap, ncclient parsing server hello
#35  Server  →  Client   130 bytes   (encrypted — ]]>]]> framing delimiter)
#36  Client  →  Server   [ACK]
#37  Client  →  Server   146 bytes   (encrypted)
#38  Server  →  Client   178 bytes   (encrypted)
#39  Client  →  Server   1314 bytes  NETCONF client <hello> + <rpc><get> (encrypted)
```

This is the phase that separates NETCONF from SSH/CLI. After the channel is open, the SSH subsystem name `netconf` is requested rather than `shell` or `exec`. The server immediately sends its NETCONF `<hello>` message.

**NETCONF `<hello>` (packet 33, 658 bytes):** The server must advertise all NETCONF capabilities it supports before any RPC can be issued. This is mandatory per RFC 6241 — both sides exchange capability lists and neither can send an RPC until the peer's `<hello>` is received. The server's list includes base NETCONF capabilities and Arista-specific capabilities. At 658 bytes on the wire, this is the NETCONF protocol's mandatory overhead — SSH/CLI has no equivalent. The size reflects XML's verbosity: a binary encoding of the same capability list would be a fraction of this size.

**ncclient request (packet 39, 1314 bytes):** ncclient sends two XML documents concatenated: the client `<hello>` advertising its own capabilities, followed by the `<rpc>` request — a `<get>` with a subtree filter selecting the `openconfig-interfaces:interfaces` namespace. The entire request is XML:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<hello xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <capabilities>
    <capability>urn:ietf:params:netconf:base:1.0</capability>
  </capabilities>
</hello>
]]>]]>
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="urn:uuid:..." xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <get>
    <filter type="subtree">
      <interfaces xmlns="http://openconfig.net/yang/interfaces"/>
    </filter>
  </get>
</rpc>
]]>]]>
```

The `]]>]]>` delimiter (11 bytes) is NETCONF's end-of-message marker in base:1.0 framing — a fixed string that terminates each XML document. This is visible in the encrypted packet length alongside the XML content.

### Phase 6 — Server Processing (~187ms, packets 40–41)

```
#40  Server  →  Client   [ACK only]   — 41ms gap
     ← 146ms gap — EOS translating OpenConfig YANG + serialising XML →
#41  Server  →  Client   1566 bytes   first TCP segment of XML response
```

After acknowledging the request, the server goes silent for **187ms total** (41ms + 146ms). This is the deepest server-side processing stack of all six methods:

1. The YANG model traversal (same as RESTCONF and gNMI) maps EOS native interface state through the OpenConfig interfaces schema
2. The result is serialised to XML — which is significantly more verbose than JSON due to mandatory closing tags, namespace declarations on every element, and attribute syntax

This is ~55ms longer than RESTCONF's processing time (which also does YANG translation but outputs JSON) and ~155ms longer than eAPI. The XML serialisation cost is the difference between RESTCONF's 56ms and NETCONF's 187ms processing time.

### Phase 7 — XML Response (~215ms, packets 41–1,123)

```
#41    Server  →  Client   1566 bytes   (start of XML response)
#42    Client  →  Server   [ACK]
#43    Server  →  Client   1566 bytes
#44    Client  →  Server   [ACK]
... 841 more S→C segments of 1566 bytes, ACK'd in pairs ...
#1123  Server  →  Client   466 bytes   (final XML segment including ]]>]]> delimiter)
#1124  Client  →  Server   [ACK]        (SACK {157622:158022}, win 29 — selective ack of retransmitted segment)
#1125  Client  →  Server   [ACK]        (window update only: win 29 → 61, length 0 — client drained buffer, advertising more space)
```

**Total response payload: ~156,368 bytes (~156KB)**

This is the single most striking measurement in the entire benchmark. Compared to the same query via other methods:

| Method      | Response size      |
|-------------|--------------------|
| SSH/CLI     | 784 bytes          |
| eAPI        | 2,373 bytes        |
| RESTCONF    | 23,209 bytes       |
| gNMI        | 41,414 bytes       |
| **NETCONF** | **~156,368 bytes** |

NETCONF's response is **~66× larger than eAPI** for the same interface data. The size explosion comes from XML's inherent verbosity: every field requires an opening tag, a closing tag, and explicit namespace declarations on each element. The OpenConfig YANG hierarchy adds container nesting (`config`, `state`, `subinterfaces`, etc.), and NETCONF wraps everything in `<rpc-reply>`, `<data>`, and outer namespace declarations. Where eAPI returns `"linkStatus": "connected"`, NETCONF XML returns:

```xml
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name>Ethernet1</name>
    <state>
      <oper-status>UP</oper-status>
    </state>
  </interface>
</interfaces>
```

...repeated for every interface, every counter, every config field, with full namespace strings on each element.

The 845 TCP segments are transmitted in a rapid burst — TCP handles segmentation automatically. The 215ms transmission time for 156KB on a local subnet is dominated by round-trip ACK latency rather than bandwidth.

### Phase 8 — Session Teardown (~137ms, packets 1,126–1,130)

```
#1126  Client  →  Server   322 bytes   SSH close + NETCONF <close-session> (encrypted)
#1127  Server  →  Client   274 bytes   (encrypted response)
#1128  Client  →  Server   [ACK]
#1129  Server  →  Client   242 bytes   (encrypted — SSH channel close)
#1130  Client  →  Server   [ACK+RST]
```

ncclient sends a NETCONF `<close-session>` RPC followed by the SSH channel close sequence. The client terminates with an RST rather than a clean FIN — the same pattern seen in the Python `requests`-based captures.

### Timing Breakdown

| Phase                                  | Packets         | Duration    |
|----------------------------------------|-----------------|-------------|
| TCP handshake                          | #1–3            | ~0.07ms     |
| SSH banner exchange                    | #4–7            | ~28ms       |
| SSH key exchange                       | #8–16           | ~90ms       |
| SSH authentication                     | #17–28          | ~56ms       |
| Password auth (server-side)            | —               | ~1,474ms    |
| SSH channel + NETCONF hello            | #29–39          | ~52ms       |
| Server processing (YANG + XML)         | #40–41          | ~187ms      |
| XML response (156KB, 845 segments)     | #41–1,123       | ~215ms      |
| Session teardown                       | #1,126–1,130    | ~137ms      |
| **Total**                              |                 | **~2,240ms**|

### Why NETCONF Is the Most Verbose Method

Three compounding factors:

1. **Same SSH auth cost as SSH/CLI (1,474ms):** NETCONF runs inside SSH, so the full password authentication penalty applies — no way to avoid it.
2. **NETCONF hello overhead:** Both sides must complete a capability exchange before any RPC can proceed. This is a protocol requirement with no equivalent in eAPI, RESTCONF, or gNMI.
3. **XML response size (156KB):** XML's tag-pair verbosity and mandatory namespace declarations on every element produce a response ~66× larger than eAPI. The same OpenConfig data that RESTCONF returns as 23KB of JSON becomes 156KB of XML. Every additional TCP segment adds latency through the ACK cycle.

In environments using NETCONF operationally, response size is managed through subtree filters (requesting only specific nodes rather than the full interfaces tree), chunked framing (base:1.1), and persistent sessions (eliminating the SSH handshake and hello exchange per query). The 156KB response measured here represents the worst case: a full OpenConfig interfaces tree dump over a fresh connection.

---

## 6. Telnet/CLI — Netmiko

**Port:** 23 | **Protocol:** Telnet (RFC 854) | **Total packets:** 95 | **Measured time:** ~6,444ms

> **Security note:** Telnet carries no encryption. Every packet in this capture — including username, password, and command output — is visible as plaintext in Wireshark. This is not a Wireshark decryption exercise: there is nothing to decrypt.

### Overview: Why Telnet Is the Slowest

Telnet's slowness has nothing to do with the absence of encryption (no TLS means *less* work, not more). The bottleneck is Netmiko's sleep-based approach to Telnet option negotiation and prompt detection. Netmiko inserts fixed `time.sleep()` delays at multiple points during the IAC negotiation and login sequence — each one adding hundreds of milliseconds of idle waiting before a single meaningful byte is exchanged.

The total IAC sleep overhead alone is approximately **3,400ms** out of the total ~6,444ms. The actual data transfer is trivially fast.

### Phase 1 — TCP 3-Way Handshake (~0.05ms, packets 1–3)

```
#1   Client  →  Server   [SYN]     port 49232 → 23
#2   Server  →  Client   [SYN-ACK]
#3   Client  →  Server   [ACK]
```

Standard TCP handshake to port 23. No TLS context to initialise, no SSL library overhead — Netmiko connects a raw socket directly. This completes faster than any other method.

### Phase 2 — IAC Option Negotiation Round 1 (~992ms, packets 4–13)

Telnet uses **IAC (Interpret As Command)** sequences to negotiate terminal options before data flows. IAC is byte `0xFF` (255), followed by a command byte and an option byte. The options are visible in plaintext:

```
#4   Server  →  Client   78 bytes
     ff fd 18  — IAC DO  TERMINAL-TYPE
     ff fd 20  — IAC DO  TERMINAL-SPEED
     ff fd 23  — IAC DO  X-DISPLAY-LOCATION
     ff fd 27  — IAC DO  NEW-ENVIRON
#5   Client  →  Server   [ACK]
     ← 992ms gap — Netmiko sleep() before responding →
#6   Client  →  Server   69 bytes   ff fc 18  — IAC WONT TERMINAL-TYPE
#7   Server  →  Client   [ACK]
#8   Client  →  Server   69 bytes   ff fc 20  — IAC WONT TERMINAL-SPEED
#9   Server  →  Client   [ACK]
#10  Client  →  Server   69 bytes   ff fc 23  — IAC WONT X-DISPLAY-LOCATION
#11  Server  →  Client   [ACK]
#12  Client  →  Server   69 bytes   ff fc 27  — IAC WONT NEW-ENVIRON
#13  Server  →  Client   [ACK]
```

The server sends four `DO` requests (asking the client to enable terminal features). The client declines all four with `WONT` responses. This is expected — Netmiko's Telnet client does not implement terminal type negotiation.

The **992ms gap** between packet 4 and packet 6 is a `time.sleep(1)` call in Netmiko's Telnet handler. Netmiko waits a full second before responding to the server's IAC options. SSH has no equivalent of this — SSH option negotiation is handled by paramiko synchronously in microseconds.

### Phase 3 — IAC Option Negotiation Round 2 (~501ms, packets 14–22)

```
#14  Server  →  Client   81 bytes
     ff fb 03  — IAC WILL SUPPRESS-GO-AHEAD
     ff fd 01  — IAC DO   ECHO
     ff fd 1f  — IAC DO   NAWS (Window Size)
     ff fb 05  — IAC WILL STATUS
     ff fd 21  — IAC DO   LINEMODE
#15  Client  →  Server   [ACK]
     ← 501ms gap — Netmiko sleep() before responding →
#16  Client  →  Server   69 bytes   ff fe 03  — IAC DONT SUPPRESS-GO-AHEAD
#17  Server  →  Client   69 bytes   ff fb 03  — IAC WILL SUPPRESS-GO-AHEAD  (server insists)
#18  Client  →  Server   78 bytes
     ff fc 01  — IAC WONT ECHO
     ff fc 1f  — IAC WONT NAWS
     ff fe 05  — IAC DONT STATUS
     ff fc 21  — IAC WONT LINEMODE
#19  Server  →  Client   69 bytes   ff fb 01  — IAC WILL ECHO  (server will handle echo)
#20  Client  →  Server   [ACK]       — 41ms gap
#21  Server  →  Client   76 bytes   "Username: "
#22  Client  →  Server   [ACK]
```

Another round of IAC negotiation. The **501ms gap** before packet 16 is another `time.sleep()` call. The server then sends the `Username:` prompt — the first human-readable content in the session, at approximately 1,543ms elapsed.

At this point all IAC negotiation is complete. The terminal options were never actually negotiated to anything useful; the sequence exists because Arista EOS's Telnet server sends standard RFC 854 option requests, and Netmiko must respond before the server will send the login prompt.

### Phase 4 — Username Entry (~460ms, packets 23–26)

```
     ← 460ms gap — Netmiko sleep() before sending username →
#23  Client  →  Server   69 bytes   ff fe 03  — IAC DONT SUPPRESS-GO-AHEAD
#24  Server  →  Client   [ACK]       — 42ms gap (server processes)
#25  Client  →  Server   75 bytes   ff fe 01 61 64 6d 69 6e 0d
                                    — IAC DONT ECHO, then "admin\r"
#26  Server  →  Client   [ACK]
```

The **460ms gap** is another Netmiko sleep. Packet 25 is particularly interesting: it combines an IAC `DONT ECHO` command with the username `admin\r` in a single packet — `ff fe 01` followed immediately by `61 64 6d 69 6e 0d` (ASCII "admin" + carriage return).

**The username is fully visible in plaintext in Wireshark.** The hex decode is unambiguous: `0x61 0x64 0x6d 0x69 0x6e` = `a d m i n`.

### Phase 5 — Password Entry (~951ms, packets 27–31)

```
#27  Server  →  Client   76 bytes   "Password: "
#28  Client  →  Server   [ACK]
     ← 951ms gap — Netmiko sleep() before sending password →
#29  Client  →  Server   72 bytes   61 64 6d 69 6e 0d  — "admin\r"
#30  Server  →  Client   68 bytes   (echo — \r\n)
#31  Client  →  Server   [ACK]
```

The **951ms gap** is another sleep. Packet 29 carries the password in plaintext: `61 64 6d 69 6e 0d` = `admin\r`. No encryption, no hashing — the password is transmitted verbatim over the wire.

In contrast, SSH encrypts everything after the NEWKEYS exchange (packet 12 in the SSH/CLI capture). The password itself is never transmitted — only a hash comparison is performed server-side, and even that happens inside the encrypted channel. Telnet offers no such protection.

### Phase 6 — Server Authentication + Banner (~1,658ms, packets 32–48)

```
     ← 1,516ms gap — server verifying credentials + sending login info →
#32  Server  →  Client   116 bytes  "Last login: Sat Mar 21 18:35:27 from 172.20.20.1"
#33  Client  →  Server   [ACK]
#34  Server  →  Client   70 bytes   "C2A>"    ← device prompt (user privilege level)
#35  Client  →  Server   [ACK]
     ← 343ms gap — Netmiko processing, prepares to enter enable mode →
#36  Client  →  Server   72 bytes   "admin\r"  ← Netmiko sends enable password attempt
#37  Server  →  Client   68 bytes   "ad"       ← server echo
#38  Client  →  Server   [ACK]
#39  Server  →  Client   69 bytes   "min"      ← echo continues
     ... echo completes ...
#43  Server  →  Client   81 bytes   "% Invalid input"
#44  Client  →  Server   [ACK]
#47  Server  →  Client   70 bytes   "C2A>"    ← prompt returned
#48  Client  →  Server   [ACK]
```

The **1,516ms gap** is the server verifying the password — the same credential check that SSH/CLI takes 1,474ms for. The actual timing is nearly identical because both ultimately invoke the same PAM/AAA stack on EOS. In SSH, this gap is hidden inside the encrypted auth channel; in Telnet, it's simply silence between plaintext packets.

After the prompt appears, Netmiko attempts to enter privileged mode by sending the enable password (`admin\r`). EOS at the `>` prompt level interprets this as a CLI command — which does not exist — and returns `% Invalid input`. Netmiko detects the prompt after the error and continues.

Note that the server echoes commands character-by-character in small packets (68 bytes, 69 bytes frame lengths for 2–3 byte payloads) — this is Telnet's character-mode echo, visible in packets 37–42. SSH hides all of this inside the encrypted channel.

### Phase 7 — Session Preparation (~994ms, packets 49–81)

```
     ← 994ms gap — Netmiko sleep() before sending terminal setup →
#49  Client  →  Server   68 bytes   "\r\n"
#50  Server  →  Client   68 bytes   (echo)
     ...
#54  Client  →  Server   86 bytes   "terminal width 511\r"
#55–61: Server echoes command + "Width set to 511 columns." + prompt
#67  Client  →  Server   85 bytes   "terminal length 0\r"
#68–70: Server echoes + "terminal length 0\nPagination disabled.\nC2A>"
     ... additional prompt-detection round trips (#71–81) ...
```

The **994ms gap** is another Netmiko sleep between prompt detection and sending the terminal setup commands. Netmiko then sends `terminal width 511` and `terminal length 0` (disable paging) — the same session preparation it performs over SSH, but here fully visible in plaintext. Each command produces a round-trip echo cycle that SSH hides inside the encrypted channel.

### Phase 8 — Command Execution and Response (~110ms, packets 82–95)

```
#82  Client  →  Server   90 bytes   "show interfaces status\r"
#83  Server  →  Client   70 bytes   "show"  ← echo starts
#84  Client  →  Server   [ACK]       — 40ms gap (server processing command)
#85  Server  →  Client   821 bytes  command output (plaintext)
#86  Client  →  Server   [ACK]
#87  Client  →  Server   68 bytes   "\r\n"
#88  Server  →  Client   68 bytes   (echo)
     ... Netmiko reads until prompt detected ...
#90  Server  →  Client   70 bytes   "C2A>"  ← prompt confirms output complete
#92  Client  →  Server   72 bytes   "exit\r"
#93  Client  →  Server   [FIN+ACK]
#94  Server  →  Client   [FIN+ACK]
#95  Client  →  Server   [ACK]
```

The `show interfaces status` command output arrives in a single 821-byte packet — completely readable in Wireshark, no decryption required:

```
Port       Name    Status       Vlan     Duplex Speed  Type
Et1                connected    1        full   1G     ...
...
```

**Total response payload: 755 bytes** — similar to SSH/CLI's 784 bytes. Both return the same tabular text because both ultimately run the same EOS CLI command and receive its text output. Neither performs YANG translation.

The connection teardown (packets 93–95) is a clean 4-way FIN — Telnet has no higher-level close protocol unlike gNMI's GOAWAY or NETCONF's `<close-session>`.

### Timing Breakdown

| Phase                                | Packets  | Duration     |
|--------------------------------------|----------|--------------|
| TCP handshake                        | #1–3     | ~0.05ms      |
| Server IAC round 1                   | #4–5     | ~9ms         |
| Netmiko sleep #1                     | —        | ~992ms       |
| Client WONT responses                | #6–13    | ~1ms         |
| Server IAC round 2                   | #14–15   | ~1ms         |
| Netmiko sleep #2                     | —        | ~501ms       |
| IAC exchanges + Username prompt      | #16–22   | ~42ms        |
| Netmiko sleep #3                     | —        | ~460ms       |
| Username entry                       | #23–26   | ~42ms        |
| Password prompt + Netmiko sleep #4   | #27–29   | ~951ms       |
| Password entry                       | #29–31   | ~1ms         |
| Server auth + banner + prompt        | —        | ~1,516ms     |
| Netmiko session prep + sleep #5      | #32–81   | ~1,795ms     |
| Command + response                   | #82–92   | ~110ms       |
| TCP teardown                         | #93–95   | ~0.3ms       |
| **Total**                            |          | **~6,444ms** |

### Why Telnet Is Slowest — and Why Encryption Isn't the Reason

The absence of TLS actually makes Telnet *faster* at the transport layer — no certificate exchange, no key derivation, no cipher computation. Yet Telnet takes 6.4 seconds versus SSH/CLI's 1.9 seconds.

The difference is entirely **Netmiko's sleep-based IAC handling**:

| Sleep                    | Duration  | Reason                                                        |
|--------------------------|-----------|---------------------------------------------------------------|
| Before WONT responses    | ~992ms    | Fixed `time.sleep()` waiting for IAC sequence to complete     |
| Before DONT responses    | ~501ms    | Fixed `time.sleep()` before second negotiation round          |
| Before sending username  | ~460ms    | Fixed `time.sleep()` after receiving login prompt             |
| Before sending password  | ~951ms    | Fixed `time.sleep()` after receiving password prompt          |
| Before terminal setup    | ~994ms    | Fixed `time.sleep()` in session preparation                   |

**Total sleep overhead: ~3,898ms out of ~6,444ms total (~60%).**

Netmiko's sleep approach exists because Telnet provides no reliable signal for "option negotiation complete" — unlike SSH which has explicit NEWKEYS and channel setup messages. Netmiko uses conservative fixed sleeps to avoid sending data before the server is ready. The alternative (event-driven IAC parsing) exists in libraries like `asyncio`/`telnetlib3` but would require rewriting Netmiko's Telnet backend.

The actual data transfer — the 755-byte command response — takes under 50ms. Everything else is waiting.

**Security summary:** Beyond the performance cost, Telnet is unacceptable for production use. Username, password, all commands, and all output are transmitted in plaintext. Any observer on the network path — or reading this pcap file — can see the complete session without any tools beyond Wireshark's default view.

---

## Cross-Method Analysis

### Response Size

The same interface data returned by each method, measured in bytes on the wire:

| Method    | Response size    | Relative to eAPI |
|-----------|------------------|------------------|
| SSH/CLI   | 784 bytes        | 0.3×             |
| Telnet    | 755 bytes        | 0.3×             |
| eAPI      | 2,373 bytes      | 1×               |
| RESTCONF  | 23,209 bytes     | ~10×             |
| gNMI      | 41,414 bytes     | ~17×             |
| NETCONF   | ~156,368 bytes   | ~66×             |

CLI methods (SSH, Telnet) return the smallest payloads because they return raw text output — no structure overhead, just the table as printed. eAPI returns compact native JSON. RESTCONF and gNMI return standards-compliant OpenConfig JSON with full YANG namespace annotations and container hierarchies. NETCONF's XML multiplies that same YANG structure by the verbosity factor of angle-bracketed tag pairs on every field.

The gNMI response is larger than RESTCONF's despite both querying the same YANG model because `encoding="json_ietf"` wraps the JSON data inside protobuf gNMI Notification/Update envelopes. `encoding="proto"` would make gNMI the most compact of all standards-based methods — but this cEOS version supports only `json`, `json_ietf`, and `ascii`; proto encoding requires physical EOS hardware.

### Server Processing Time

Time the device spent computing the response, measured as silence between request acknowledgement and first response byte:

| Method   | Server processing | Cost driver                                 |
|----------|-------------------|---------------------------------------------|
| eAPI     | ~32ms             | Native EOS command execution, direct JSON   |
| RESTCONF | ~56ms             | YANG model traversal + JSON serialisation   |
| gNMI     | ~73ms             | YANG traversal + protobuf encoding          |
| NETCONF  | ~187ms            | YANG traversal + XML serialisation          |
| SSH/CLI  | ~40ms (per cmd)   | CLI execution only, no model work           |
| Telnet   | ~40ms             | CLI execution only, no model work           |

The ~24ms gap between eAPI and RESTCONF is a direct measurement of OpenConfig model translation cost. The further ~130ms from RESTCONF to NETCONF is the cost of XML serialisation over JSON for the same model data. gNMI's two-phase processing (encoding half the response, sending it, then encoding the rest) is visible in the capture: a ~73ms gap before burst 1, and a ~23ms gap between bursts while the server encodes the second half.

### Where the Time Goes

| Method   | Total  | Handshake / session setup | Auth / IAC sleeps | Server processing | Response TX |
|----------|--------|---------------------------|-------------------|-------------------|-------------|
| eAPI     | ~97ms  | ~57ms (SSL ctx + TLS)     | —                 | ~32ms             | ~7ms        |
| RESTCONF | ~110ms | ~50ms (SSL ctx + TLS)     | —                 | ~56ms             | ~2ms        |
| gNMI     | ~234ms | ~20ms (TLS + HTTP2)       | —                 | ~73ms             | ~28ms tx + ~73ms decode |
| SSH/CLI  | ~1,967ms| ~74ms (banner + kex)    | ~1,476ms (passwd) | ~40ms             | ~200ms prep + ~150ms cmd |
| NETCONF  | ~2,240ms| ~170ms (banner + kex)   | ~1,474ms (passwd) | ~187ms            | ~215ms      |
| Telnet   | ~6,444ms| ~1ms (raw TCP)          | ~3,898ms (sleeps) + ~1,516ms (passwd) | ~40ms | ~110ms |

For API-based methods (eAPI, RESTCONF, gNMI), the dominant cost is split between client-side setup and server-side processing. For SSH-based methods, password authentication dominates — accounting for 75% of SSH/CLI time and 65% of NETCONF time. For Telnet, Netmiko's sleep delays consume 60% of total time before any command is sent.

### Key Findings

**eAPI is the fastest because it does the least work.** No model translation, no protocol negotiation overhead beyond TLS, and the smallest response payload. For operational polling of Arista-specific data, it is the right default choice.

**RESTCONF and gNMI trade raw speed for standards compliance.** Both query the same OpenConfig YANG model and return structured, vendor-neutral data. The overhead — ~24–41ms of additional server processing and ~10–17× larger payloads — buys portability across vendors and compatibility with OpenConfig tooling.

**SSH authentication processing is the single largest bottleneck** across SSH/CLI and NETCONF. At ~1.47 seconds, it accounts for the majority of both methods' total time. Key-based authentication was tested and measured at ~1,932ms — no improvement — because on this cEOS platform EOS applies the same ~1.47s server-side auth processing delay regardless of auth method (see key-auth note in the SSH/CLI section).

**NETCONF's 156KB XML response** is the extreme case of a well-known trade-off: XML is human-readable, schema-validated, and unambiguous, but pays a steep verbosity tax. In production, subtree filters and chunked framing (NETCONF base:1.1) reduce payload size dramatically; persistent sessions eliminate the SSH handshake and hello exchange per query.

**gNMI is architecturally the best fit for streaming telemetry.** The one-time setup cost (TLS handshake, HTTP/2 SETTINGS) amortises across a persistent channel. With `path_cert` pre-pinning the device certificate (as in this benchmark), the additional cert-retrieval TCP session pygnmi would otherwise open is already eliminated. On physical EOS hardware — which supports `encoding="proto"` unlike this cEOS lab platform — the JSON-in-protobuf overhead drops further, making gNMI the highest-throughput method for continuous data collection.

**Telnet should not exist in production networks.** The plaintext credential exposure is a hard security disqualifier independent of performance. The 6.4-second round trip is a secondary concern.

### Protocol Reference

| Method   | Port | Transport              | Data format            | Encryption        | Model layer       |
|----------|------|------------------------|------------------------|-------------------|-------------------|
| eAPI     | 443  | HTTP/1.1 over TLS 1.3  | JSON-RPC (native EOS)  | TLS 1.3           | None (CLI passthrough) |
| RESTCONF | 6020 | HTTP/1.1 over TLS 1.3  | YANG-compliant JSON    | TLS 1.3           | OpenConfig YANG   |
| gNMI     | 6030 | gRPC / HTTP/2 / TLS 1.3| Protobuf (+ JSON opt.) | TLS 1.3 (BoringSSL) | OpenConfig YANG |
| SSH/CLI  | 22   | SSHv2 (paramiko)       | Plain text (CLI output)| SSHv2             | None              |
| NETCONF  | 830  | SSH subsystem (RFC 6242)| XML (YANG-compliant)  | SSHv2             | OpenConfig YANG   |
| Telnet   | 23   | Raw TCP (RFC 854)      | Plain text (CLI output)| **None**          | None              |

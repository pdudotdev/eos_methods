## Wireshark filters
| Method | Wireshark Filter |
|---|---|
| SSH/CLI | `tcp.port == 22` |
| eAPI | `tcp.port == 443` |
| RESTCONF | `tcp.port == 6020` |
| NETCONF | `tcp.port == 830` |
| gNMI | `tcp.port == 6030` |
| Telnet/CLI | `tcp.port == 23` |

## Quick note on RESTCONF, gNMI, eAPI
These three methods use TLS. To help Wireshark decrypt the captured traffic, we need to dump the TLS session keys to a file as each connection is made. Then point Wireshark at `~/tls_keys.log` under **Edit → Preferences → Protocols → TLS → (Pre)-Master-Secret log filename**.
```
export SSLKEYLOGFILE=~/tls_keys.log
python arista.py
cat ~/tls_keys.log
```
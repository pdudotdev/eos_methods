## Wireshark filters
| Method | Wireshark Filter |
|---|---|
| SSH/CLI | `tcp.port == 22` |
| eAPI | `tcp.port == 443` |
| RESTCONF | `tcp.port == 6020` |
| NETCONF | `tcp.port == 830` |
| gNMI | `tcp.port == 6030` |
| SNMPv3 | `udp.port == 161` |
| Telnet/CLI | `tcp.port == 23` |

## TLS decryption (eAPI, RESTCONF)
`arista.py` automatically writes TLS session keys to `pcaps/tls_keys.log` via `SSLKEYLOGFILE`. To decrypt in Wireshark: **Edit → Preferences → Protocols → TLS → (Pre)-Master-Secret log filename** → point to `pcaps/tls_keys.log`.

Override the default path if needed:
```
export SSLKEYLOGFILE=~/tls_keys.log
python arista.py
```

**Note:** gNMI uses pygnmi (BoringSSL) which does not honor `SSLKEYLOGFILE` — gNMI traffic cannot be decrypted this way.

## SNMPv3 capture
SNMPv3 uses UDP/161. The USM headers (engine ID, username, auth/priv parameters) are visible in cleartext, but the PDU payload is encrypted (AES-128). Wireshark can decode the SNMPv3 framing natively — to decrypt the payload, add the USM credentials in **Edit → Preferences → Protocols → SNMP → Users Table**:
- Username: `benchmark`
- Auth protocol: SHA
- Auth password: `admin1234`
- Priv protocol: AES
- Priv password: `admin1234`
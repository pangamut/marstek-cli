# marstek_cli

A Python command-line tool to query and control **Marstek Venus E/C** home battery systems via their local UDP Open API (Rev 2.0) — no cloud, no internet required.

## Features

- **Auto-Discovery**: finds Marstek devices on your LAN via UDP broadcast
- **Full status readout**: device info, WiFi, Bluetooth, battery, energy system, meter, operating mode
- **Control commands**: set operating mode, depth of discharge, LED panel, Bluetooth broadcasting
- **Link auto-detection**: measures RTT on first contact and automatically adds inter-query delays on WiFi
- **No dependencies**: pure Python standard library

## Requirements

- Python 3.10+
- Marstek Venus E or C with **Open API enabled** in the Marstek mobile app
- Device and host on the same local network

## Installation

```bash
# No installation needed — just download and run
curl -O https://raw.githubusercontent.com/pangamut/marstek-cli/main/marstek_cli.py
chmod +x marstek_cli.py
```

## Usage

### Auto-Discovery

```bash
python3 marstek_cli.py
```

Broadcasts on the LAN and lists all responding Marstek devices. If only one is found, connects automatically.

### Direct connection

```bash
python3 marstek_cli.py 192.168.1.100
```

### Query a specific section

```bash
python3 marstek_cli.py <ip> --query es       # Energy system (SOC, power flows)
python3 marstek_cli.py <ip> --query bat      # Battery (capacity, temperature)
python3 marstek_cli.py <ip> --query em       # Energy meter / CT (phase powers)
python3 marstek_cli.py <ip> --query mode     # Current operating mode
python3 marstek_cli.py <ip> --query wifi     # WiFi status
python3 marstek_cli.py <ip> --query ble      # Bluetooth status
python3 marstek_cli.py <ip> --query device   # Device info (model, firmware, MACs)
```

Single-section queries return immediately with no inter-query delay.

### Full status readout

```bash
python3 marstek_cli.py <ip>
```

Queries all seven sections in sequence. On first contact, the tool probes link latency and automatically selects an appropriate inter-query delay (see [Link auto-detection](#link-auto-detection) below).

### Set commands

```bash
# Switch operating mode
python3 marstek_cli.py <ip> --set-mode auto
python3 marstek_cli.py <ip> --set-mode ai
python3 marstek_cli.py <ip> --set-mode ups
python3 marstek_cli.py <ip> --set-mode passive --power 300   # discharge at 300 W

# Set depth of discharge (30–88%)
python3 marstek_cli.py <ip> --set-dod 40

# LED panel
python3 marstek_cli.py <ip> --set-led off

# Bluetooth broadcasting
python3 marstek_cli.py <ip> --set-ble off
```

Destructive commands (`--set-mode`, `--set-dod`) ask for confirmation before executing.

### Machine-readable output

```bash
python3 marstek_cli.py <ip> --query es --json
```

Emits a single JSON object with a `timestamp`, `device_ip`, `port`, and `data` key. In JSON mode, `battery_power_w` is `null` when the battery is in standby (not `0`) — the distinction matters for automation logic.

## Link auto-detection

Over **Ethernet**, the device responds in ~10–100 ms and handles back-to-back queries without issue. Over **WiFi**, the firmware drops UDP packets that arrive within ~3.7 s of the previous response, causing systematic timeouts on full readouts.

When running a full status readout (no `--query`), the tool sends a single probe request and measures the round-trip time:

- RTT **< 150 ms** → Ethernet detected → no inter-query delay
- RTT **≥ 150 ms** or timeout → WiFi detected → 4.0 s delay between sections

The selected mode is shown at the start of the output:

```
  Link: Ethernet (RTT 82 ms < 150 ms → no delay)
```
```
  Link: WiFi (RTT 210 ms ≥ 150 ms → delay 4.0 s)
```

### Overriding the delay

If auto-detection is not suitable for your setup, the delay can be fixed in two ways:

**Command line** (good for scripts and cron jobs):

```bash
python3 marstek_cli.py <ip> --delay 4.0   # force WiFi-safe delay
python3 marstek_cli.py <ip> --delay 0     # force no delay
```

**Constant in the script** (good for permanent installations — edit once):

```python
FORCE_DELAY = 4.0   # set to None to re-enable auto-detection
```

Priority order: `--delay` > `FORCE_DELAY` > auto-detection.

## Example output

```
Marstek CLI  •  Auto-Discovery  •  07:38:57

  Scanning LAN for Marstek devices …
  1 device(s) found:

  [1]  VenusE 3.0      IP: 192.168.1.100     FW: 144  MAC: xxxxxxxxxxxx

  → VenusE 3.0 @ 192.168.1.100

  Link: Ethernet (RTT 82 ms < 150 ms → no delay)

────────────────────────────────────────────────────────
  Energy System — ES.GetStatus
────────────────────────────────────────────────────────
  SOC                                      31 %
  Battery capacity                         5.12 kWh
  Battery power                            —
  PV power                                 0 W
  Grid (+ import / − export)               0 W
  Off-grid power                           0 W

  Total PV generated                       0 Wh
  Total grid export                        1.95 kWh
  Total grid import                        391 Wh
  Total load / off-grid                    0 Wh
```

## Operating modes

| Mode | Description |
|------|-------------|
| `Auto` | Automatic charge/discharge based on grid and PV |
| `AI` | AI-optimised scheduling |
| `Manual` | Time-based schedule (configurable via app) |
| `Passive` | Fixed discharge power set externally |
| `UPS` | Uninterruptible power supply mode |

## Device quirks

Confirmed behaviours of the **Venus E, FW 144** — not API documentation issues:

- **WiFi rate-limit (~3.7 s)**: The firmware silently drops UDP requests arriving within approximately 3.7 s of the previous successful response. No error is returned — the packet is simply ignored. This only affects back-to-back queries; the link auto-detection handles it automatically.

- **`bat_power` absent in standby**: When the battery is neither charging nor discharging, `ES.GetStatus` omits `bat_power` entirely rather than returning `null`. The CLI displays `—`; JSON output emits `null`.

- **CT state mismatch**: `ES.GetMode` reports `ct_state: 0` (no CT) even when an external CT is connected and `EM.GetStatus` correctly reports `ct_state: 1`. The two fields refer to different CT inputs — internal vs. external.

- **Cumulative CT energy counters always 0**: `input_energy` and `output_energy` in both `ES.GetMode` and `EM.GetStatus` always return `0` on the Venus E. This appears to be unsupported on this model.

- **Undocumented `wifi_mac` field**: `Wifi.GetStatus` includes a `wifi_mac` field not listed in the Rev 2.0 spec. It matches the MAC returned by `Marstek.GetDevice`.

- **Typo booleans**: The firmware occasionally returns `"ture"` instead of `true` for boolean set-result confirmations. The CLI handles this transparently via `to_bool()`.

- **Response `id: 0` on internal errors**: On certain internal firmware states, the device responds with `id: 0` regardless of the request ID. The `api_check` tool classifies these as errors.

## API reference

Based on the official **Marstek Device Open API Rev 2.0** (January 2026).  
Available at: `https://static-eu.marstekenergy.com/ems/resource/agreement/MarstekDeviceOpenApi.pdf`

### Protocol

- Transport: **UDP** (default port `30000`)
- Format: **JSON-RPC**
- Scope: local LAN only — the Open API must be enabled once via the Marstek app

### Supported commands (Venus C/E)

| Command | Type | Description |
|---------|------|-------------|
| `Marstek.GetDevice` | Read | Device info, firmware, MACs |
| `Wifi.GetStatus` | Read | WiFi connection details |
| `BLE.GetStatus` | Read | Bluetooth state |
| `Bat.GetStatus` | Read | Battery SOC, capacity, temperature |
| `ES.GetStatus` | Read | Power flows, energy totals |
| `ES.GetMode` | Read | Current mode + CT data |
| `ES.SetMode` | Write | Set operating mode |
| `EM.GetStatus` | Read | CT phase powers + cumulative energy |
| `DOD.SET` | Write | Set depth of discharge (30–88%) |
| `Led.Ctrl` | Write | LED panel on/off |
| `Ble.Adv` | Write | Bluetooth broadcasting on/off |

---

## marstek_api_check

A companion diagnostic tool that probes every known API command, measures round-trip timing, logs raw payloads, detects type anomalies, and stress-tests the device.

```bash
python3 marstek_api_check.py <ip>
python3 marstek_api_check.py <ip> --rounds 10 --report results.json
python3 marstek_api_check.py <ip> --raw
python3 marstek_api_check.py <ip> --stress --rounds 50
python3 marstek_api_check.py <ip> --command ES.GetMode
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--rounds N` | 5 | Probe repetitions per command |
| `--delay S` | 3.5 | Seconds between probes — must exceed ~3.7 s on WiFi to avoid the rate-limit |
| `--timeout S` | 4.0 | UDP receive timeout per probe |
| `--raw` | off | Print raw request/response JSON for each probe |
| `--report FILE` | — | Save full JSON report (timing + type analysis) to file |
| `--stress` | off | Force 0.05 s delay — intentionally triggers the rate-limit to characterise its behaviour |
| `--command CMD` | all | Probe only a single command (e.g. `Bat.GetStatus`) |

### What it checks

For each command the tool records RTT, detects missing or wrongly-typed response fields against the Rev 2.0 spec, flags undocumented fields, and catches firmware typos. The summary table shows per-command success rate, average/min/max/σ RTT, and any anomalies found.

A `--report` JSON file contains the full per-probe records including raw request and response payloads, suitable for offline analysis.

## License

MIT

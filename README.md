# marstek_cli

A Python command-line tool to query and control **Marstek Venus E/C** home battery systems via their local UDP Open API (Rev 2.0) — no cloud, no internet required.

## Features

- **Auto-Discovery**: finds Marstek devices on your LAN via UDP broadcast
- **Full status readout**: device info, WiFi, Bluetooth, battery, energy system, meter, operating mode
- **Control commands**: set operating mode, depth of discharge, LED panel, Bluetooth broadcasting
- **Rate-limit aware**: automatically waits between section queries to respect the device's ~3.3 s internal rate-limit window
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

Single-section queries are unaffected by the rate-limit delay and return immediately.

### Full status readout

```bash
python3 marstek_cli.py <ip>
```

Queries all seven sections in sequence. Due to the device's ~3.3 s rate-limit (see [Device quirks](#device-quirks)), each section is separated by a 3.5 s pause — total runtime is approximately 22 s. Use `--query` for faster single-section polling.

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

Emits a single JSON object with a `timestamp`, `device_ip`, `port`, and `data` key. Suitable for piping into Home Assistant scripts or logging pipelines. In JSON mode, `battery_power_w` is `null` when the battery is in standby (not `0`) — the distinction matters for automation logic.

## Example output

```
Marstek CLI  •  Auto-Discovery  •  07:38:57

  Suche nach Marstek-Geräten im LAN …
  1 Gerät(e) gefunden:

  [1]  VenusE 3.0      IP: 10.1.5.60         FW: 144  MAC: 60b34d8a01bd

  → VenusE 3.0 @ 10.1.5.60

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
| `Passive` | Fixed discharge power set externally (e.g. Home Assistant) |
| `UPS` | Uninterruptible power supply mode |

## Device quirks

These are confirmed behaviours of the **Venus E, FW 144** — not API documentation issues:

- **~3.3 s rate-limit**: The firmware silently ignores UDP requests that arrive within approximately 3.3 s of the previous successful response. There is no error — the packet is simply dropped. Both tools account for this: `marstek_cli.py` waits 3.5 s between section calls in full-query mode; `marstek_api_check.py` uses a 4.0 s timeout and 3.5 s inter-probe delay by default.

- **`bat_power` absent in standby**: When the battery is neither charging nor discharging, `ES.GetStatus` omits `bat_power` entirely rather than returning `null`. The CLI displays `—`; the JSON output emits `null`.

- **CT state mismatch**: `ES.GetMode` reports `ct_state: 0` (no CT) even when an external CT (e.g. Shelly Pro 3EM) is connected and `EM.GetStatus` correctly reports `ct_state: 1`. The two fields refer to different CT inputs — internal vs. external.

- **Cumulative CT energy counters always 0**: `input_energy` and `output_energy` in both `ES.GetMode` and `EM.GetStatus` always return `0` on the Venus E. This appears to be unsupported hardware on this model.

- **`wifi_mac` in `Wifi.GetStatus`**: The response includes a `wifi_mac` field not documented in the Rev 2.0 spec. It matches the MAC from `Marstek.GetDevice`.

- **Typo booleans**: The firmware occasionally returns the string `"ture"` instead of `true` for boolean set-result confirmations. The CLI handles this via `to_bool()`.

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

## Home Assistant integration

The `Passive` mode is designed for external control — ideal for zero-feed-in regulation from Home Assistant via a Shelly Pro 3EM:

```
Shelly Pro 3EM  →  HA reads grid power every 1s
                →  HA automation calculates target discharge power
                →  UDP Passive command sent to Marstek every 5–10s
```

Keep the HA polling interval for status reads (e.g. `--query es`) at **≥ 4 s** to avoid hitting the device rate-limit. For zero-feed-in control, sending a single `--set-mode passive --power <W>` command every 5–10 s is well within this budget.

A Home Assistant automation blueprint for this use case is planned.

---

## marstek_api_check

A companion diagnostic tool that probes every known API command, measures round-trip timing, logs raw payloads, and stress-tests the device.

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
| `--delay S` | 3.5 | Seconds between probes — must exceed ~3.3 s to avoid the device rate-limit |
| `--timeout S` | 4.0 | UDP receive timeout per probe |
| `--raw` | off | Print raw request/response JSON for each probe |
| `--report FILE` | — | Save full JSON report (timing + type analysis) to file |
| `--stress` | off | Force 0.05 s delay — intentionally triggers the rate-limit to measure its effect |
| `--command CMD` | all | Probe only a single command (e.g. `Bat.GetStatus`) |

### What it checks

For each command the tool records RTT, detects missing or wrongly-typed fields against the Rev 2.0 spec, flags unexpected fields, and catches firmware typos (`"ture"`, `"flase"`). The summary table shows per-command success rate, average/min/max/σ RTT, and any anomalies found.

## License

MIT| `UPS` | Uninterruptible power supply mode |

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


## Notes

- `bat_power` in `ES.GetStatus` returns `null` when the battery is in standby (neither charging nor discharging) — this is expected behaviour
- `ES.GetMode` CT state reflects the Marstek's **internal** CT input; `EM.GetStatus` reflects the **external** CT (e.g. Shelly Pro 3EM) — these are independent
- Cumulative CT energy counters (`input_energy`, `output_energy`) appear to be unsupported on the Venus E hardware and always return 0

## License

MIT

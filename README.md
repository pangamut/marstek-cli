# marstek_cli

A Python command-line tool to query and control **Marstek Venus E/C** home battery systems via their local UDP Open API (Rev 2.0) — no cloud, no internet required.

## Features

- **Auto-Discovery**: finds Marstek devices on your LAN via UDP broadcast
- **Full status readout**: device info, WiFi, Bluetooth, battery, energy system, meter, operating mode
- **Control commands**: set operating mode, depth of discharge, LED panel, Bluetooth broadcasting
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

A German localisation is also available as `marstek_cli_de.py`.

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

## Example output

```
Marstek CLI  •  Auto-Discovery  •  07:38:57

  Suche nach Marstek-Geräten im LAN …
  1 Gerät(e) gefunden:

  [1]  VenusE 3.0      IP: 10.1.5.60         FW: 144  MAC: 60b49d8601af

  → VenusE 3.0 @ 10.1.5.60

──────────────────────────────────────────────────────
  Energy System — ES.GetStatus
──────────────────────────────────────────────────────
  SOC                                      31 %
  Batteriekapazität                        5.12 kWh
  Batterieleistung                         —
  PV-Leistung                              0 W
  Netz (+ Bezug / − Einspeisung)           0 W
  Offgrid-Leistung                         0 W

  Gesamt PV erzeugt                        0 Wh
  Gesamt Netzeinspeisung                   1.95 kWh
  Gesamt Netzbezug                         391 Wh
  Gesamt Last/Offgrid                      0 Wh
```

## Operating modes

| Mode | Description |
|------|-------------|
| `Auto` | Automatic charge/discharge based on grid and PV |
| `AI` | AI-optimised scheduling |
| `Manual` | Time-based schedule (configurable via app) |
| `Passive` | Fixed discharge power set externally (e.g. Home Assistant) |
| `UPS` | Uninterruptible power supply mode |

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

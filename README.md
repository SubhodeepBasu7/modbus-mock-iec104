# modbus-mock-iec104

**Controllable Modbus TCP server that simulates an IEC104 grid-operator interface**

> ⚠️ This is **not** a real IEC104 server. It is a Modbus TCP simulation / control
> server whose register map is derived from an IEC104 grid-operator interface.
> Communication happens exclusively over **Modbus TCP**.

---

## Purpose

`modbus-mock-iec104` is a local test gateway / simulator between a grid-operator-facing
interface and an EMS-side Modbus client.

- The **grid operator** (or a test engineer) writes setpoint / command registers
  through the **browser UI** at `http://localhost:8000`.
- The **EMS-side** Modbus client reads the current setpoints and writes back
  measurement / feedback values over Modbus TCP on port **5020**.
- Both views are kept in sync in real time.

### Active power, reactive power, and apparent power

Only **active power P** and **reactive power Q** are real setpoints.  
Apparent power **S = √(P² + Q²)** is a derived / measured value and is
**never** a setpoint. The UI and the EMS-simulation helper reflect this.

---

## Quick start

### Build

```bash
docker compose build
```

### Run

```bash
docker compose up
```

The container exposes:

| Interface   | Address             |
|-------------|---------------------|
| Web UI      | http://localhost:8000 |
| Modbus TCP  | localhost:5020 unit-ID 1 |

### Stop

```bash
docker compose down
```

---

## Web UI

Open `http://localhost:8000` in a browser.

Sections:
1. **Grid Operator Setpoints & Commands** – writable registers for the grid operator.
2. **Feedback Registers** – read-only EMS response values.
3. **Live EMS Measurements** – read-only real-time measurements from the EMS.
4. **Polling / Config Registers** – writable polling configuration.
5. **EMS Simulation Helper** – convenience form to populate all measurement
   registers at once.
6. **Raw Register Table** – every register with raw hex/dec and engineering values.
7. **Write History** – last 50 register writes (source, old/new values).

The UI auto-refreshes every second and **never overwrites an input field while
the user is actively editing it**.

---

## REST API

All endpoints are documented at `http://localhost:8000/docs` (Swagger UI).

### GET `/api/health`
Returns server status.

### GET `/api/registers`
Returns all register definitions with current engineering values.

### GET `/api/registers/{address}`
Returns one register with its current value.

### POST `/api/registers/{address}`
Write an engineering value to a register.

```bash
# Turn on active-power setpoint
curl -s -X POST http://localhost:8000/api/registers/11040 \
     -H "Content-Type: application/json" \
     -d '{"value": 1, "source": "ui"}'

# Set active-power setpoint to 500 kW
curl -s -X POST http://localhost:8000/api/registers/11042 \
     -H "Content-Type: application/json" \
     -d '{"value": 500, "source": "ui"}'

# Turn on reactive-power Q kVar setpoint
curl -s -X POST http://localhost:8000/api/registers/11010 \
     -H "Content-Type: application/json" \
     -d '{"value": 1, "source": "ui"}'

# Set reactive-power Q kVar setpoint to 250 kVar
curl -s -X POST http://localhost:8000/api/registers/11012 \
     -H "Content-Type: application/json" \
     -d '{"value": 250, "source": "ui"}'
```

### POST `/api/registers/bulk`
Write multiple registers in one call.

```bash
curl -s -X POST http://localhost:8000/api/registers/bulk \
     -H "Content-Type: application/json" \
     -d '{
           "source": "ui",
           "values": {
             "11040": 1,
             "11042": 500,
             "11010": 1,
             "11012": 250
           }
         }'
```

### GET `/api/history`
Returns recent register changes (timestamp, source, address, old/new raw, engineering value).

### POST `/api/reset`
Resets all registers to their default (zero) values.

### POST `/api/simulate/ems`
Convenience endpoint that writes all EMS measurement registers from a single payload.

```bash
curl -s -X POST http://localhost:8000/api/simulate/ems \
     -H "Content-Type: application/json" \
     -d '{
           "active_power_kw": 500,
           "reactive_power_kvar": 200,
           "voltage_v": 400,
           "current_a": 100,
           "frequency_hz": 50.0,
           "soc_percent": 80
         }'
```

---

## Modbus TCP usage

Host: `localhost`  Port: `5020`  Unit ID: `1`

Only **holding registers** (function codes 3 / 6 / 16) are used.

### Factor / encoding rules

| Data type | Registers | Encoding |
|-----------|-----------|---------|
| `BIT`     | 1         | Raw = bitfield |
| `uint16`  | 1         | Raw = engineering / factor |
| `int16`   | 1         | Raw = signed 16-bit |
| `int32`   | 2         | Big-endian: high word at address, low word at address+1 |
| `uint32`  | 2         | Big-endian: high word at address, low word at address+1 |

**CosPhi** factor 1000: engineering value 0.95 → raw register value 950.  
**Frequency** factor 0.01: raw 5000 → engineering value 50.00 Hz.

### Example (pymodbus Python client)

```python
import struct
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient("localhost", port=5020)
client.connect()

# Write uint16 – active power setpoint ON
client.write_register(11040, 1, slave=1)

# Write uint16 – active power setpoint 500 kW
client.write_register(11042, 500, slave=1)

# Write int32 – active power measurement 500 kW
# Big-endian: pack as 32-bit signed, split into two 16-bit words
value = 500
packed = struct.pack(">i", value)
high = struct.unpack(">H", packed[0:2])[0]
low  = struct.unpack(">H", packed[2:4])[0]
client.write_registers(10060, [high, low], slave=1)

# Read back
rr = client.read_holding_registers(10060, count=2, slave=1)
decoded = struct.unpack(">i", struct.pack(">HH", rr.registers[0], rr.registers[1]))[0]
print("Active power:", decoded, "kW")

client.close()
```

---

## Register map

### Polling / Config (writable)

| Address | Name | Type | Factor | Unit | Description |
|---------|------|------|--------|------|-------------|
| 10000 | PollIntervall_Trigger | BIT | 1 | - | b0=Deactivated, b1=Cyclic, b2=On data change |
| 10001 | PollIntervall_ms | uint16 | 1 | ms | Polling interval 500–1200 ms |

### EMS Measurements (read-only, written by EMS Modbus client)

| Address | Name | Type | Factor | Unit | Description |
|---------|------|------|--------|------|-------------|
| 10010 | LineCurrent_Frequency | uint16 | 0.01 | Hz | Grid frequency |
| 10011 | LineCurrent_Amperage_1 | int32 | 1 | A | Phase L1 current |
| 10013 | LineCurrent_Amperage_2 | int32 | 1 | A | Phase L2 current |
| 10015 | LineCurrent_Amperage_3 | int32 | 1 | A | Phase L3 current |
| 10017 | LineCurrent_Voltage_1 | int32 | 1 | V | Phase L1 voltage |
| 10019 | LineCurrent_Voltage_2 | int32 | 1 | V | Phase L2 voltage |
| 10021 | LineCurrent_Voltage_3 | int32 | 1 | V | Phase L3 voltage |
| 10030–10033 | FeedIn_ActivePower_P_* | uint16 | 1 | kW | Feed-in active power |
| 10040–10043 | FeedIn_ReactivePower_Q_* | uint16 | 1 | kVar | Feed-in reactive power |
| 10050–10053 | FeedIn_ApparentPower_S_* | uint16 | 1 | kVA | Feed-in apparent power |
| 10060 | ActivePower_P | int32 | 1 | kW | Active power (setpoint-driven) |
| 10062 | ReactivePower_Q | int32 | 1 | kVar | Reactive power (setpoint-driven) |
| 10064 | ApparentPower_S | int32 | 1 | kVA | Apparent power = √(P²+Q²) |
| 10070 | CosPhi | uint16 | 1000 | - | CosPhi × 1000 |
| 10080–10085 | StateOfCharge_* | uint16 | 1 | Wh/% | Battery state of charge |

### Grid Operator Setpoints (writable from UI)

| Address | Name | Type | Factor | Unit | Description |
|---------|------|------|--------|------|-------------|
| 11000 | ReactivePower_SetPoint_QU_ON_OFF | uint16 | 1 | - | Q(U) ON/OFF |
| 11002 | ReactivePower_SetPoint_QU_Voltage | uint16 | 1 | kV | Q(U) voltage setpoint |
| 11010 | ReactivePower_SetPoint_Q_kVar_ON_OFF | uint16 | 1 | - | Q kVar ON/OFF |
| 11012 | ReactivePower_SetPoint_Q_kVar | uint16 | 1 | kVar | Q setpoint in kVar |
| 11020 | ReactivePower_SetPoint_Q_percent_ON_OFF | uint16 | 1 | - | Q % ON/OFF |
| 11022 | ReactivePower_SetPoint_Q_percent | uint16 | 1 | % | Q setpoint in % |
| 11030 | CosPhi_SetPoint_ON_OFF | uint16 | 1 | - | CosPhi ON/OFF |
| 11032 | CosPhi_SetPoint | uint16 | 1000 | - | CosPhi × 1000 |
| 11040 | ActivePower_SetPoint_P_ON_OFF | uint16 | 1 | - | Active power P ON/OFF |
| 11042 | ActivePower_SetPoint_P_kW | uint16 | 1 | kW | P setpoint in kW |
| 11050 | ActivePower_SetPoint_P_percent_ON_OFF | uint16 | 1 | - | P % ON/OFF |
| 11052 | ActivePower_SetPoint_P_percent | uint16 | 1 | % | P setpoint in % |
| 11060 | ControlStage_SetPoint_percent_ON_OFF | uint16 | 1 | - | Control stage ON/OFF |
| 11062 | ControlStage_SetPoint_percent | BIT | 1 | % | b0=0%, b1=30%, b2=60%, b3=100% |
| 11070–11076 | ControlStage_*_SetPoint_ON_OFF | uint16 | 1 | - | Individual stage commands |

### Feedback Registers (read-only, written by EMS Modbus client)

| Address | Name | Description |
|---------|------|-------------|
| 11001 | ReactivePower_Feedback_QU_ON_OFF | Q(U) feedback |
| 11011 | ReactivePower_Feedback_Q_kVar_ON_OFF | Q kVar feedback |
| 11021 | ReactivePower_Feedback_Q_percent_ON_OFF | Q % feedback |
| 11031 | CosPhi_Feedback_ON_OFF | CosPhi feedback |
| 11041 | ActivePower_Feedback_P_ON_OFF | Active power P feedback |
| 11063 | ControlStage_Feedback_percent | Control stage bitfield feedback |
| 11071–11077 | ControlStage_*_Feedback_ON_OFF | Individual stage feedback |

---

## Running tests locally (without Docker)

```bash
# Install dependencies
pip install -r requirements.txt

# Run API tests
pytest tests/test_api.py -v

# Run Modbus client test (server must be running first)
python -m app.main &
sleep 2
python tests/test_modbus_client.py
```

---

## Project structure

```
app/
  main.py            – asyncio entry-point (starts both servers)
  modbus_server.py   – pymodbus async TCP server
  register_store.py  – thread-safe shared register store
  register_map.py    – YAML config loader
  schemas.py         – Pydantic models
  web.py             – FastAPI routes
  static/
    index.html       – Single-page UI
    app.js           – UI logic
    style.css        – Styling
config/
  registers.yaml     – Register definitions
tests/
  test_api.py        – pytest API integration tests
  test_modbus_client.py – Modbus client demonstration
Dockerfile
docker-compose.yml
requirements.txt
README.md
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODBUS_HOST` | `0.0.0.0` | Modbus server bind address |
| `MODBUS_PORT` | `5020` | Modbus TCP port |
| `WEB_HOST` | `0.0.0.0` | Web server bind address |
| `WEB_PORT` | `8000` | Web UI / API port |
| `UNIT_ID` | `1` | Modbus unit / slave ID |
| `ENFORCE_ACCESS_CONTROL` | `false` | If `true`, read-only registers cannot be written via UI/API |

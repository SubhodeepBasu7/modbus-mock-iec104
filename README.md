# modbus-mock-iec104

Web UI for visualizing and writing the GGW3/IEC104 Modbus register map exposed by a remote adapter-owned Modbus TCP server.

This project does not start a Modbus server. It connects as a Modbus TCP client to the server configured by `MODBUS_HOST`, `MODBUS_PORT`, and `UNIT_ID`.

## Runtime Model

- `adapter_fwt_wago_ggw3` runs the production Modbus TCP server.
- `modbus-mock-iec104` runs only the web UI and REST API.
- The UI reads/writes registers through Modbus TCP.

Typical RevPi setup:

```text
RevPi
  adapter_fwt_wago_ggw3  -> Modbus TCP server on localhost:5020
  modbus-mock-iec104     -> Web UI on 0.0.0.0:8005, connects to localhost:5020

PC browser
  http://<revpi-ip>:8005
```

## Run With Docker Compose

```bash
docker compose up -d
```

Open:

```text
http://localhost:8005
```

If running on the RevPi and accessing from your PC:

```text
http://<revpi-ip>:8005
```

## Configuration

Environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MODBUS_HOST` | `localhost` | Remote adapter Modbus server host |
| `MODBUS_PORT` | `5020` | Remote adapter Modbus server port |
| `UNIT_ID` | `1` | Modbus unit ID |
| `WEB_HOST` | `0.0.0.0` | Web UI bind host |
| `WEB_PORT` | `8005` | Web UI bind port |
| `REGISTER_CSV_PATH` | `/app/config/registers.csv` | Register map CSV |
| `ENFORCE_ACCESS_CONTROL` | `false` | Reject UI writes to read-only registers when `true` |

## Local Development

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the UI:

```bash
python -m app.main
```

Run tests:

```bash
python -m pytest -q
```

## API

The UI serves Swagger docs at:

```text
http://localhost:8005/docs
```

Useful endpoints:

- `GET /api/health`
- `GET /api/registers`
- `GET /api/registers/{address}`
- `POST /api/registers/{address}`
- `POST /api/registers/bulk`
- `POST /api/simulate/ems`
- `GET /api/history`


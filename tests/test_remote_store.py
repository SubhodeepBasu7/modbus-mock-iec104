from app.remote_store import RemoteModbusRegisterStore
from app.schemas import RegisterDefinition


class FakeModbusClient:
    def __init__(self, host, port, unit_id, auto_open, auto_close, timeout):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.values = {}

    def read_holding_registers(self, address, count):
        return [self.values.get(address + offset, 0) for offset in range(count)]

    def write_single_register(self, address, value):
        self.values[address] = value
        return True

    def write_multiple_registers(self, address, values):
        for offset, value in enumerate(values):
            self.values[address + offset] = value
        return True


def _definition(address=10011, name="Grid_Amperage_1", datatype="int32"):
    return RegisterDefinition(
        address=address,
        name=name,
        description="test register",
        datatype=datatype,
        byteorder="bigE",
        factor=1.0,
        unit="A",
        access="readwrite",
        role="ems_measurement",
    )


def test_remote_store_reads_register_values_from_modbus(monkeypatch):
    monkeypatch.setattr("app.remote_store.ModbusClient", FakeModbusClient)
    store = RemoteModbusRegisterStore(host="192.0.2.10", port=5020, unit_id=1)
    store.initialize([_definition()])
    store.client.values[10011] = 0
    store.client.values[10012] = 123

    response = store.get_register_value(10011)

    assert response.raw_value == [0, 123]
    assert response.engineering_value == 123.0


def test_remote_store_writes_engineering_values_to_modbus(monkeypatch):
    monkeypatch.setattr("app.remote_store.ModbusClient", FakeModbusClient)
    store = RemoteModbusRegisterStore(host="192.0.2.10", port=5020, unit_id=1)
    store.initialize([_definition(address=10001, name="PollIntervall_ms", datatype="uint16")])

    store.set_engineering_value(10001, 1000, source="ui")

    assert store.client.values[10001] == 1000
    history = store.get_history()
    assert history[0].name == "PollIntervall_ms"
    assert history[0].new_raw == 1000

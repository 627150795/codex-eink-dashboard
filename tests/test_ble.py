import asyncio
import unittest

from codex_eink.ble import BleTransport, DeviceStatus


class FakeClient:
    def __init__(self, notification):
        self.notification = notification
        self.writes = []
        self.is_connected = True

    async def start_notify(self, _uuid, callback):
        callback(0, bytearray(self.notification))

    async def stop_notify(self, _uuid):
        return None

    async def write_gatt_char(self, _uuid, data, response=False):
        self.writes.append(bytes(data))

    async def disconnect(self):
        self.is_connected = False


def status_packet(resolution_type=2, is_bwr=False):
    packet = bytearray(16)
    packet[10] = resolution_type | ((1 if is_bwr else 0) << 4)
    packet[11] = 12
    packet[12] = 0x74
    packet[13] = 0x0E
    return bytes(packet)


class BleTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_decoding(self):
        status = DeviceStatus.from_notification(status_packet(2))
        self.assertEqual(status.resolution, (296, 128))
        self.assertEqual(status.firmware_version, 1.2)
        self.assertAlmostEqual(status.voltage, 3.7)

    async def test_invalid_status_causes_no_writes(self):
        client = FakeClient(b"short")
        transport = BleTransport()
        with self.assertRaises(ValueError):
            await transport.upload_with_client(client, [b"packet"], expected_resolution=(296, 128))
        self.assertEqual(client.writes, [])

    async def test_resolution_mismatch_causes_no_writes(self):
        client = FakeClient(status_packet(0))
        transport = BleTransport()
        with self.assertRaises(ValueError):
            await transport.upload_with_client(client, [b"packet"], expected_resolution=(296, 128))
        self.assertEqual(client.writes, [])


if __name__ == "__main__":
    unittest.main()

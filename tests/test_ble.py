import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

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
    def _fake_bleak(self, scanner, client=None):
        module = types.ModuleType("bleak")
        module.BleakScanner = scanner
        if client is not None:
            module.BleakClient = client
        return patch.dict(sys.modules, {"bleak": module})

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

    async def test_find_device_uses_address_lookup_when_address_is_configured(self):
        device = types.SimpleNamespace(address="AA:BB", name="SKD-CLOCK")
        scanner = Mock()
        scanner.find_device_by_address = AsyncMock(return_value=device)
        scanner.discover = AsyncMock(return_value=[])

        with self._fake_bleak(scanner):
            found = await BleTransport(address="AA:BB", scan_timeout=3.5)._find_device()

        self.assertIs(found, device)
        scanner.find_device_by_address.assert_awaited_once_with("AA:BB", timeout=3.5)
        scanner.discover.assert_not_awaited()

    async def test_find_device_uses_name_filter_when_address_is_not_configured(self):
        device = types.SimpleNamespace(address="AA:BB", name=None)
        scanner = Mock()
        scanner.find_device_by_filter = AsyncMock(return_value=device)
        scanner.discover = AsyncMock(return_value=[])

        with self._fake_bleak(scanner):
            found = await BleTransport(name_prefix="SKD-CLOCK", scan_timeout=2.0)._find_device()

        self.assertIs(found, device)
        scanner.find_device_by_filter.assert_awaited_once()
        filter_fn = scanner.find_device_by_filter.await_args.args[0]
        self.assertTrue(filter_fn(types.SimpleNamespace(name="SKD-CLOCK-1"), types.SimpleNamespace(local_name=None)))
        self.assertTrue(filter_fn(types.SimpleNamespace(name=None), types.SimpleNamespace(local_name="SKD-CLOCK-2")))
        self.assertFalse(filter_fn(types.SimpleNamespace(name=None), types.SimpleNamespace(local_name="OTHER")))
        self.assertEqual(scanner.find_device_by_filter.await_args.kwargs["timeout"], 2.0)
        scanner.discover.assert_not_awaited()

    async def test_find_device_preserves_timeout_message_when_no_device_matches(self):
        scanner = Mock()
        scanner.find_device_by_filter = AsyncMock(return_value=None)

        with self._fake_bleak(scanner), self.assertRaises(TimeoutError) as error:
            await BleTransport(name_prefix="SKD-CLOCK")._find_device()

        self.assertEqual(
            str(error.exception),
            "e-ink device not found (name prefix 'SKD-CLOCK'); wait for its advertising window or press its button",
        )

    async def test_with_client_reuses_discovered_device_after_transient_failure(self):
        device = types.SimpleNamespace(address="AA:BB", name="SKD-CLOCK")
        scanner = Mock()
        scanner.find_device_by_filter = AsyncMock(return_value=device)

        class FakeBleakClient:
            devices = []
            exited = []

            def __init__(self, connected_device):
                self.device = connected_device
                self.devices.append(connected_device)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                self.exited.append(self.device)

        callback_attempts = 0

        async def flaky_callback(client):
            nonlocal callback_attempts
            callback_attempts += 1
            if callback_attempts == 1:
                raise RuntimeError("temporary GATT failure")
            return client.device

        with self._fake_bleak(scanner, FakeBleakClient), patch("codex_eink.ble.asyncio.sleep", new=AsyncMock()):
            result = await BleTransport().with_client(flaky_callback, retries=1)

        self.assertIs(result, device)
        self.assertEqual(scanner.find_device_by_filter.await_count, 1)
        self.assertEqual(FakeBleakClient.devices, [device, device])
        self.assertEqual(FakeBleakClient.exited, [device, device])

    async def test_with_client_does_not_repeat_a_failed_full_scan(self):
        transport = BleTransport()
        transport._find_device = AsyncMock(side_effect=TimeoutError("not advertising"))

        with self._fake_bleak(Mock(), Mock()), self.assertRaisesRegex(TimeoutError, "not advertising"):
            await transport.with_client(AsyncMock(), retries=2)

        transport._find_device.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

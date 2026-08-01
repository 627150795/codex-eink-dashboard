from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, TypeVar

from .models import SUPPORTED_RESOLUTIONS


SERVICE_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"

T = TypeVar("T")


@dataclass(frozen=True)
class DeviceStatus:
    resolution_type: int
    resolution: tuple[int, int]
    is_bwr: bool
    firmware_version: float
    voltage: float
    temperature: int
    allow_bluetooth: bool
    registered: bool

    @classmethod
    def from_notification(cls, payload: bytes | bytearray) -> "DeviceStatus":
        if len(payload) < 16:
            raise ValueError(f"device status is too short: {len(payload)} bytes")
        resolution_type = payload[10] & 0x0F
        if resolution_type >= len(SUPPORTED_RESOLUTIONS):
            raise ValueError(f"unknown resolution type: {resolution_type}")
        return cls(
            resolution_type=resolution_type,
            resolution=SUPPORTED_RESOLUTIONS[resolution_type],
            is_bwr=bool(payload[10] >> 4),
            firmware_version=payload[11] / 10.0,
            voltage=(payload[12] | (payload[13] << 8)) / 1000.0,
            temperature=int(payload[14]),
            allow_bluetooth=bool(payload[9] >> 4),
            registered=bool(payload[15]),
        )


class BleTransport:
    def __init__(
        self,
        *,
        name_prefix: str = "SKD-CLOCK",
        address: str | None = None,
        scan_timeout: float = 12.0,
        status_timeout: float = 8.0,
    ):
        self.name_prefix = name_prefix
        self.address = address
        self.scan_timeout = scan_timeout
        self.status_timeout = status_timeout

    async def _read_status(self, client) -> DeviceStatus:
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def callback(_sender, data):
            if not future.done():
                try:
                    future.set_result(DeviceStatus.from_notification(data))
                except Exception as exc:
                    future.set_exception(exc)

        await client.start_notify(NOTIFY_UUID, callback)
        try:
            return await asyncio.wait_for(future, timeout=self.status_timeout)
        finally:
            try:
                await client.stop_notify(NOTIFY_UUID)
            except Exception:
                pass

    def _check_mtu(self, client) -> None:
        mtu_size = getattr(client, "mtu_size", None)
        if isinstance(mtu_size, int) and mtu_size > 0 and mtu_size < 132:
            raise RuntimeError(f"negotiated BLE MTU {mtu_size} cannot carry a 129-byte frame")

    async def write_packets(self, client, packets: Iterable[bytes], *, expected_resolution: tuple[int, int], status: DeviceStatus) -> None:
        if status.resolution != tuple(expected_resolution):
            raise ValueError(f"device resolution {status.resolution} does not match frame {tuple(expected_resolution)}")
        self._check_mtu(client)
        for packet in packets:
            if len(packet) > 129:
                raise ValueError("protocol packet exceeds 129 bytes")
            await client.write_gatt_char(WRITE_UUID, bytes(packet), response=True)

    async def upload_with_client(self, client, packets: Iterable[bytes], *, expected_resolution: tuple[int, int]) -> DeviceStatus:
        status = await self._read_status(client)
        await self.write_packets(client, packets, expected_resolution=expected_resolution, status=status)
        return status

    async def _find_device(self):
        try:
            from bleak import BleakScanner
        except ImportError as exc:
            raise RuntimeError("Bleak is not installed; run install.ps1 first") from exc
        if self.address:
            device = await BleakScanner.find_device_by_address(self.address, timeout=self.scan_timeout)
        else:
            device = await BleakScanner.find_device_by_filter(
                lambda device, advertisement_data: (
                    device.name or advertisement_data.local_name or ""
                ).startswith(self.name_prefix),
                timeout=self.scan_timeout,
            )
        if device is not None:
            return device
        target = self.address or f"name prefix {self.name_prefix!r}"
        raise TimeoutError(f"e-ink device not found ({target}); wait for its advertising window or press its button")

    async def with_client(self, callback: Callable[..., Awaitable[T]], *, retries: int = 1) -> T:
        """Open one BLE connection, run callback(client), retry transient transport failures."""
        try:
            from bleak import BleakClient
        except ImportError as exc:
            raise RuntimeError("Bleak is not installed; run install.ps1 first") from exc

        # Discovery failures should return to the outer scheduler instead of
        # multiplying the full scan timeout. Connection/GATT retries reuse the
        # discovered device for this one upload attempt.
        device = await self._find_device()
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                async with BleakClient(device) as client:
                    return await callback(client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Bleak raises platform-specific errors for GATT Invalid PDU / disconnects.
                last_error = exc
                if attempt >= retries:
                    raise
                await asyncio.sleep(min(2**attempt, 4))
        assert last_error is not None
        raise last_error

    async def probe(self) -> DeviceStatus:
        async def _run(client):
            return await self._read_status(client)

        return await self.with_client(_run, retries=1)

    async def upload(self, packets: Iterable[bytes], *, expected_resolution: tuple[int, int], retries: int = 1) -> DeviceStatus:
        saved_packets = tuple(bytes(packet) for packet in packets)

        async def _run(client):
            return await self.upload_with_client(client, saved_packets, expected_resolution=expected_resolution)

        return await self.with_client(_run, retries=retries)

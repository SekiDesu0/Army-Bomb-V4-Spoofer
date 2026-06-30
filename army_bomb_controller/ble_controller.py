import asyncio
import logging
import time
from dataclasses import dataclass

from bleak import BleakScanner, BleakClient
from bleak.backends.device import BLEDevice

from protocol import (
    DeviceType,
    UUID_MAP,
    detect_type,
    uses_write_with_response,
    build_packet,
)

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredDevice:
    address: str
    name: str
    rssi: int
    device_type: DeviceType | None


class BLEController:
    def __init__(self):
        self._client: BleakClient | None = None
        self._device_type: DeviceType | None = None
        self._char_uuid: str | None = None
        self._last_color: tuple[int, int, int] | None = None
        self._last_write_time: float = 0.0
        self._scanning = False
        self._on_device_found = None
        self._on_connected = None
        self._on_disconnected = None
        self._on_error = None
        self._write_throttle_s = 1.0 / 60.0
        self._consecutive_errors = 0

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def device_type(self) -> DeviceType | None:
        return self._device_type

    @property
    def scanning(self) -> bool:
        return self._scanning

    def set_callbacks(self, on_device_found, on_connected, on_disconnected, on_error=None):
        self._on_device_found = on_device_found
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_error = on_error

    async def start_scan(self):
        self._scanning = True

        def detection_callback(device: BLEDevice, advertisement_data):
            try:
                name = device.name or advertisement_data.local_name or ""
                dt = detect_type(name)
                if dt is not None and self._on_device_found:
                    dev = DiscoveredDevice(
                        address=device.address,
                        name=name,
                        rssi=advertisement_data.rssi or -100,
                        device_type=dt,
                    )
                    self._on_device_found(dev)
            except Exception:
                logger.exception("Error in BLE detection callback")

        try:
            scanner = BleakScanner(detection_callback=detection_callback)
            await scanner.start()
            logger.info("BLE scan started")
        except Exception:
            logger.exception("Failed to start BLE scan")
            self._scanning = False
            if self._on_error:
                self._on_error("Failed to start Bluetooth scan. Is Bluetooth enabled?")
            return

        while self._scanning:
            await asyncio.sleep(0.1)
        try:
            await scanner.stop()
            logger.info("BLE scan stopped")
        except Exception:
            logger.exception("Error stopping BLE scanner")

    def stop_scan(self):
        self._scanning = False

    async def connect(self, address: str, name: str):
        if self._client and self._client.is_connected:
            await self._client.disconnect()

        self._device_type = detect_type(name)
        if self._device_type is None:
            msg = f"Unknown device type for: {name}"
            logger.error(msg)
            raise ValueError(msg)

        _, self._char_uuid = UUID_MAP[self._device_type]

        def disconnect_handler(_client):
            logger.warning("BLE device disconnected unexpectedly: %s", _client.address)
            self._device_type = None
            self._char_uuid = None
            self._last_color = None
            if self._on_disconnected:
                self._on_disconnected()

        self._client = BleakClient(address, disconnected_callback=disconnect_handler)
        logger.info("Connecting to %s (%s)...", name, address)
        await self._client.connect()
        logger.info("Connected to %s (%s) as %s", name, address, self._device_type.value)
        self._consecutive_errors = 0
        if self._on_connected:
            self._on_connected(self._device_type)

    async def disconnect(self):
        if self._client and self._client.is_connected:
            try:
                address = self._client.address
                logger.info("Disconnecting from %s...", address)
                await self._client.disconnect()
                logger.info("Disconnected from %s", address)
            except Exception:
                logger.exception("Error during disconnect")

    async def send_color(self, r: int, g: int, b: int, brightness: int = 0xFF):
        if not self._client or not self._client.is_connected or not self._device_type:
            return False

        color = (r, g, b)
        if color == self._last_color:
            return True

        uses_response = uses_write_with_response(self._device_type)
        now = time.monotonic()
        if not uses_response and now - self._last_write_time < self._write_throttle_s:
            return True

        try:
            packet = build_packet(self._device_type, r, g, b, brightness)
            await self._client.write_gatt_char(
                self._char_uuid, packet, response=uses_response
            )
            self._last_color = color
            self._last_write_time = now
            self._consecutive_errors = 0
            return True
        except Exception:
            self._consecutive_errors += 1
            logger.exception(
                "BLE write error #%d — %s RGB(%d,%d,%d)",
                self._consecutive_errors,
                self._device_type.value,
                r, g, b,
            )
            if self._consecutive_errors >= 5:
                logger.error(
                    "Disconnecting after %d consecutive write failures",
                    self._consecutive_errors,
                )
                if self._on_error:
                    self._on_error("Device disconnected after 5 consecutive write failures")
                await self.disconnect()
            return False

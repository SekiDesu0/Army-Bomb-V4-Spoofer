from enum import Enum


class DeviceType(Enum):
    V4 = "V4"
    V3 = "V3"
    SE = "SE"
    MULTI = "Multi"


SERVICE_V4 = "0001fe01-0000-1000-8000-00805f9800c4"
CHAR_V4 = "0001ff01-0000-1000-8000-00805f9800c4"

SERVICE_OLDER = "00010203-0405-0607-0809-0a0b0c0d1911"
CHAR_OLDER = "00010203-0405-0607-0809-0a0b0c0d2b19"

UUID_MAP = {
    DeviceType.V4: (SERVICE_V4, CHAR_V4),
    DeviceType.V3: (SERVICE_OLDER, CHAR_OLDER),
    DeviceType.SE: (SERVICE_OLDER, CHAR_OLDER),
    DeviceType.MULTI: (SERVICE_OLDER, CHAR_OLDER),
}


def detect_type(name: str | None) -> DeviceType | None:
    if not name:
        return None
    name_upper = name.upper()
    if "BTS_V4" in name_upper:
        return DeviceType.V4
    if "BTS LIGHTSTICK3" in name_upper or "BTSLIGHTSTICK3" in name_upper:
        return DeviceType.V3
    if "BTS LIGHTSTICK_SE" in name_upper or "BTSLIGHTSTICK_SE" in name_upper or "BTS LIGHTSTICK SE" in name_upper:
        return DeviceType.SE
    if "MULTIM" in name_upper:
        return DeviceType.MULTI
    return None


def uses_write_with_response(device_type: DeviceType) -> bool:
    return device_type == DeviceType.V4


def build_packet(device_type: DeviceType, r: int, g: int, b: int, brightness: int = 0xFF) -> bytes:
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    brightness = max(0, min(255, brightness))

    if device_type == DeviceType.V4:
        return bytes([r, g, b, brightness])
    else:
        checksum = sum([0x0B, 0x00, 0x00, r, g, b, 0x00, 0x00]) & 0xFF
        return bytes([0x01, 0x01, 0x0B, 0x00, 0x00, r, g, b, 0x00, 0x00, checksum])

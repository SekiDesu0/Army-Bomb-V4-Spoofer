# Army Bomb V4 Spoofer — ESP32-S3 Firmware

ESP32-S3 BLE peripheral that emulates a genuine BTS Official Light Stick Ver.4 (ARMY Bomb V4).

## Hardware Requirements

- **ESP32-S3 Super Mini** (XMC flash, 4MB, 2MB PSRAM)
- **WS2812B LED** on GPIO48 (onboard on Super Mini)
- PlatformIO with Arduino framework

## LED Behavior

| State | Pattern | Meaning |
|---|---|---|
| Booting | 2 green blinks | Advertising started successfully |
| Booting | 3 red blinks | Advertising failed |
| Advertising | Blue flash (500ms on/off) | Waiting for first connection |
| Connected (fresh) | Solid blue | Connected, no color written yet |
| Connected (active) | Color | Displaying last written color |
| Disconnected (latched) | Color (steady) | After commit, ready for reconnect |

## GATT Structure

Exact match for BTS ARMY Bomb Ver.4 (verified against real device).

### Services

| Service | UUID | Source |
|---|---|---|
| LED Control | `0001fe01-0000-1000-8000-00805f9800c4` | Custom |
| Concert | `0001fe06-0000-1000-8000-00805f9800c4` | Custom |
| Custom | `0001fe02-0000-1000-8000-00805f9800c4` | Custom |
| MAC | `0001fe03-0000-1000-8000-00805f9800c4` | Custom |
| Custom | `0001fe04-0000-1000-8000-00805f9800c4` | Custom |
| Device Information | `0x180A` | Standard |
| Battery Service | `0x180F` | Standard |

### Characteristics

| Service | Char | Properties | Initial Value | Purpose |
|---|---|---|---|---|
| fe01 | `ff01` | R/W | `FF-FF-FF-00` | Color packet (4 bytes: R, G, B, transition) |
| fe01 | `ff02` | R/W | `03-00-00-00` | Effects / self-mode color / concert payload |
| fe06 | `ff13` | R/W_NR | `00` | Commit (write `01` to latch) |
| fe06 | `ff13` descriptor `0x2901` | R | `OTA` | Characteristic User Description |
| fe02 | `ff04` | R/W_NR | `00-00` | Unknown control |
| fe03 | `ff05` | R | Reversed BLE MAC | Internal MAC (little-endian bytes!) |
| fe04 | `ff06` | R | `00-00` | Unknown |
| 0x180A | `0x2A29` | R | `Elcomtec` | Manufacturer Name |
| 0x180A | `0x2A24` | R | `BTSNN26JOS900NNO` | Model Number |
| 0x180A | `0x2A26` | R | `1.1 <MAC> 0000 01` | Firmware Revision (contains MAC) |
| 0x180A | `0x2A00` | R | `BTS OFFICIAL LIGHT STICK VER.4` | Device Name (in DIS) |
| 0x180A | `0x2A00` descr. `0x2901` | R | Reversed MAC bytes | Real V4 quirk — stores MAC |
| 0x180A | `0x2A00` descr. `0x2902` | R | `00-00` | CCCD stub |
| 0x180F | `0x2A19` | R/NOTIFY | `99%` | Battery Level |

### Device Information Values (critical for official app)

These must match EXACTLY or the official BTS V4 app rejects the device:

```
Manufacturer Name   = "Elcomtec"
Model Number        = "BTSNN26JOS900NNO"   (per-device — use your real V4's value)
Firmware Revision   = "1.1 80:DE:CC:XX:XX:XX 0000 01"   (MAC embedded)
Device Name (DIS)   = "BTS OFFICIAL LIGHT STICK VER.4"   (NOT "BTS_V4 LS"!)
```

## Advertising

- **Name only**: `BTS_V4 LS`
- **No service UUIDs** in advertisement (matches real V4 — avoids 31-byte overflow)
- **Scan response enabled** (Android compatibility)

## MAC Address Spoofing

The real V4 uses the Telink/Elcomtec OUI `80:DE:CC`. The ESP32's factory MAC
(`A0:F2:62`, Espressif) is overridden via `esp_base_mac_addr_set()` **before**
BLE initialization. On ESP32-S3 the BLE MAC = base MAC + 1.

```cpp
uint8_t spoofedMac[6] = { 0x80, 0xDE, 0xCC, 0xAA, 0xBB, 0x01 };
esp_base_mac_addr_set(spoofedMac);  // before NimBLEDevice::init()
// BLE MAC → 80:DE:CC:AA:BB:02
```

> **Warning**: The real V4 MAC `80:DE:CC:...` has MSBs `10` which is **invalid**
> for BLE random addresses. Do NOT use `setOwnAddr(BLE_OWN_ADDR_RANDOM)` — it
> will crash the NimBLE stack. Use `esp_base_mac_addr_set()` instead.

## Effect Protocol (ff02)

### Self-mode: 4-byte Format

```
+------+------+------+------+
| TYPE |  R   |  G   |  B   |
+------+------+------+------+
```

| Byte 0 | Effect | LED Animation |
|---|---|---|
| `00` | OFF | Black |
| `01` | ON | Solid color |
| `02` | BLINK | Toggle fg/bg (400ms period) |
| `03` | BREATH | Sine-wave pulse (800ms period) |
| `04` | STROBE | Fast toggle fg/bg (100ms period) |

### Concert-mode: 20-byte Format (EFX v1.4)

```
[0..1]   mode (u16 LE)     = 0x0001 (effect) or 0x0005 (game)
[2..3]   ledMask (u16 LE)   = 0x0000 (all LEDs)
[4..6]   fgColor (3 × u8)   = R, G, B
[7..9]   bgColor (3 × u8)   = R, G, B
[10]     effectType (u8)     = 0=OFF, 1=ON, 2=BLINK, 3=BREATH, 4=STROBE
[11..12] durationMs (u16 LE)
[13]     period (u8)         = in 10ms units
[14]     spf (u8)            = samples per frame
[15]     randomColor (u8)    = 0 or 1
[16]     randomDelay (u8)    = 0..255 (×10ms)
[17]     fade (u8)
[18]     broadcasting (u8)   = 0 or 1
[19]     syncIndex (u8)      = re-sync counter
```

## Connection Flow (official app)

```
1. App scans for "BTS_V4 LS" + 80:DE:CC OUI
2. BLE connect → GATT service discovery
3. Read DIS           → Manufacturer, Model, Firmware, Device Name
4. Read ff05          → reversed MAC (validates against connection address)
5. Read Battery       → battery level
6. Write ff02         → self-mode color: 01 RR GG BB
       or
   Write ff02         → concert payload: 20-byte EFX frame
```

## Build & Upload

```bash
cd army_bomb_spoofer
python -m platformio run -t upload
```

### Bootloader Mode

If upload fails with "No serial data received":
1. **Hold BOOT** button
2. **Press RST** (tap once)
3. **Release RST**
4. **Release BOOT**
5. Retry upload command

### Serial Monitor

```
python -m platformio device monitor --port COM11 --baud 115200
```

The firmware prints diagnostic output with millisecond timestamps:
- `Connected (latched=N, handle=N)` — BLE connection established
- `Disconnected (reason=N, latched=N)` — BLE disconnection
- `[ffXX WRITE]` / `[ffXX READ]` — characteristic I/O
- `*** onRead/Wrote fired!` — callback activity from BLE task
- `EFX: mode=N type=N fg=(R,G,B) period=N dur=N` — effect parsed

## Configuration

### Device-specific values to change

Edit `src/main.cpp`:

- **MAC address** (line 11): Change `0xAA, 0xBB, 0x01` to any unique device bytes
- **Model Number** (line ~360): Change `BTSNN26JOS900NNO` to your real V4's value
- The firmware string builds automatically with the BLE MAC

### Making your own device unique

Each physical V4 has a unique MAC and model number. If you have multiple spoofers:
1. Give each a different MAC (keep `80:DE:CC` OUI, vary the last 3 bytes)
2. Use a different model number string

## Testing

### With nRF Connect (recommended for debugging)

1. Install **nRF Connect for Mobile** from Play Store
2. Scan → find `BTS_V4 LS`
3. Verify MAC starts with `80:DE:CC`
4. Connect → check GATT services match the table above
5. Try reading each characteristic value
6. Try writing `01 FF 00 00` to `ff02` (should turn LED red)

### With official BTS app

1. Power OFF your real V4 first
2. Turn Bluetooth OFF on phone → wait 10s → turn ON (clear GATT cache)
3. Force-stop the official "BTS Official Light Stick Ver.4" app
4. Open app → scan → BTS_V4 LS should appear
5. Connect → LED should turn blue then respond to colors/effects

### With Python controller

```bash
cd ../army_bomb_controller
pip install -r requirements.txt
python main.py
```

Click Scan → select BTS_V4 LS → Connect → use color picker.

## Dependencies

- **NimBLE-Arduino 2.5.0** — BLE stack
- **FastLED 3.10.3** — NeoPixel control
- **ESP32-S3** with Arduino framework (espressif32 platform)
- **esptool** upload protocol (not esp-builtin)

## platformio.ini

```ini
[env:esp32_s3_super_mini]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino
board_upload.flash_size = 4MB
board_build.partitions = default.csv
monitor_speed = 115200
upload_speed = 921600
upload_protocol = esptool
lib_deps =
    NimBLE-Arduino @ 2.5.0
    FastLED @ 3.10.3
```

## References

- [jjanisheck/army-light](https://github.com/jjanisheck/army-light) — Verified V4 BLE protocol (GATT map, packet format, latch/commit flow)
- [ryanDonsi/Light-Stick-SDK](https://github.com/ryanDonsi/Light-Stick-SDK) — 20-byte EFX payload v1.4 spec, effect types, game mode, OTA

## License

Educational and personal use. Use with devices you own.

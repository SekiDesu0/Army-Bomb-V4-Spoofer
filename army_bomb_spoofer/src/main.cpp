#include <NimBLEDevice.h>
#include <FastLED.h>
#include "esp_mac.h"

#define NUM_LEDS 1
CRGB leds[NUM_LEDS];

const char* DEVICE_NAME = "BTS_V4 LS";

// Spoofed MAC matching the real V4 Telink/Elcomtec OUI
uint8_t spoofedMac[6] = { 0x80, 0xDE, 0xCC, 0xAA, 0xBB, 0x01 };

// Custom service UUIDs (each is its own PRIMARY service on real V4)
const char* SVC_FE01_UUID = "0001fe01-0000-1000-8000-00805f9800c4";
const char* SVC_FE02_UUID = "0001fe02-0000-1000-8000-00805f9800c4";
const char* SVC_FE03_UUID = "0001fe03-0000-1000-8000-00805f9800c4";
const char* SVC_FE04_UUID = "0001fe04-0000-1000-8000-00805f9800c4";
const char* SVC_FE06_UUID = "0001fe06-0000-1000-8000-00805f9800c4";

// Characteristic UUIDs
const char* CHR_FF01_UUID = "0001ff01-0000-1000-8000-00805f9800c4";
const char* CHR_FF02_UUID = "0001ff02-0000-1000-8000-00805f9800c4";
const char* CHR_FF04_UUID = "0001ff04-0000-1000-8000-00805f9800c4";
const char* CHR_FF05_UUID = "0001ff05-0000-1000-8000-00805f9800c4";
const char* CHR_FF06_UUID = "0001ff06-0000-1000-8000-00805f9800c4";
const char* CHR_FF13_UUID = "0001ff13-0000-1000-8000-00805f9800c4";

NimBLEServer* pServer = nullptr;
bool bleConnected = false;
bool latched = false;
bool pendingDisconnect = false;
unsigned long disconnectTarget = 0;
uint16_t connHandle = 0;
CRGB pendingColor = CRGB(255, 255, 255);  // default white (matching real V4 ff01)

// Dynamic firmware string (built in setup with actual BLE MAC)
char g_fwString[64];

volatile uint8_t g_readFlag = 0;
volatile uint8_t g_writeFlag = 0;

// Concert-mode effect state (20-byte EFX payload)
enum EffectAnim : uint8_t { EFX_NONE, EFX_ON, EFX_OFF, EFX_STROBE, EFX_BLINK, EFX_BREATH };
struct EffectState {
    bool active = false;
    CRGB fgColor = CRGB::Black;
    CRGB bgColor = CRGB::Black;
    EffectAnim anim = EFX_NONE;
    uint8_t  period10ms = 10;   // period in 10ms units
    uint16_t durationMs = 0;
    unsigned long startMs = 0;
    bool toggle = false;        // for strobe/blink toggling
    unsigned long lastToggleMs = 0;
} g_effect;

class ColorCharCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo) override {
        g_writeFlag = 1;
        std::string data = pChar->getValue();
        Serial.printf("[%lu] [ff01 WRITE] len=%d: ", millis(), (int)data.length());
        for (size_t i = 0; i < data.length(); i++) Serial.printf("%02X ", (uint8_t)data[i]);
        Serial.println();
        if (data.length() >= 3) {
            uint8_t r = (uint8_t)data[0];
            uint8_t g = (uint8_t)data[1];
            uint8_t b = (uint8_t)data[2];
            pendingColor = CRGB(r, g, b);
            leds[0] = pendingColor;
            FastLED.show();
        }
    }
    void onRead(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo) override {
        g_readFlag = 1;
        uint8_t buf[4] = { pendingColor.r, pendingColor.g, pendingColor.b, 0 };
        pChar->setValue(buf, 4);
    }
};

class CommitCharCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo) override {
        g_writeFlag = 1;
        std::string data = pChar->getValue();
        Serial.printf("[%lu] [ff13 WRITE] len=%d: ", millis(), (int)data.length());
        for (size_t i = 0; i < data.length(); i++) Serial.printf("%02X ", (uint8_t)data[i]);
        Serial.println();
        if (data.length() >= 1 && data[0] == 0x01) {
            leds[0] = pendingColor;
            FastLED.show();
            latched = true;
            pendingDisconnect = true;
            disconnectTarget = millis() + 1500;
            Serial.println("Commit received — latched, disconnecting in 1.5s");
        }
    }
    void onRead(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo) override {
        g_readFlag = 1;
        uint8_t v = 0x00;  // real V4 returns 0x00
        pChar->setValue(&v, 1);
    }
};

class EffectsCharCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo) override {
        g_writeFlag = 1;
        std::string data = pChar->getValue();
        size_t len = data.length();

        Serial.printf("[%lu] [ff02 WRITE] len=%d: ", millis(), (int)len);
        for (size_t i = 0; i < len && i < 32; i++) Serial.printf("%02X ", (uint8_t)data[i]);
        Serial.println();

        // 4-byte effect packet: EFFECT_TYPE R G B
        // Effect types: 0=OFF, 1=ON, 2=STROBE, 3=BLINK, 4=BREATH
        if (len >= 4) {
            uint8_t fx = (uint8_t)data[0];
            uint8_t r = (uint8_t)data[1];
            uint8_t g = (uint8_t)data[2];
            uint8_t b = (uint8_t)data[3];

            if (fx >= 1 && fx <= 4) {  // ON, STROBE, BLINK, BREATH have color
                pendingColor = CRGB(r, g, b);
            }

            // Start effect animation
            g_effect.fgColor = CRGB(r, g, b);
            g_effect.bgColor = CRGB::Black;
            g_effect.period10ms = (fx == 4) ? 10 : (fx == 2) ? 60 : 200; // strobe, blink, breath
            g_effect.durationMs = 0;
            g_effect.startMs = millis();
            g_effect.toggle = false;
            g_effect.lastToggleMs = 0;
            g_effect.active = true;

            // App effect codes: 0=OFF, 1=ON, 2=BLINK, 3=BREATH, 4=STROBE
            switch (fx) {
                case 0: g_effect.anim = EFX_OFF;    break;
                case 1: g_effect.anim = EFX_ON;     break;
                case 2: g_effect.anim = EFX_BLINK;  break;
                case 3: g_effect.anim = EFX_BREATH; break;
                case 4: g_effect.anim = EFX_STROBE; break;
                default: g_effect.anim = EFX_OFF;   break;
            }

            Serial.printf("  Self-mode effect=%d RGB(%d,%d,%d) anim=%d\n", fx, r, g, b, g_effect.anim);
            return;
        }

        // 20-byte concert-mode EFX payload (EFX v1.4)
        if (len >= 20) {
            uint16_t mode = (uint8_t)data[0] | ((uint8_t)data[1] << 8);
            uint8_t fgR = (uint8_t)data[4];
            uint8_t fgG = (uint8_t)data[5];
            uint8_t fgB = (uint8_t)data[6];
            uint8_t bgR = (uint8_t)data[7];
            uint8_t bgG = (uint8_t)data[8];
            uint8_t bgB = (uint8_t)data[9];
            uint8_t fxType = (uint8_t)data[10];
            uint16_t durMs = (uint8_t)data[11] | ((uint8_t)data[12] << 8);
            uint8_t period = (uint8_t)data[13];

            pendingColor = CRGB(fgR, fgG, fgB);

            if (mode == 1) {  // MODE_EFFECT_PAYLOAD
                g_effect.fgColor = CRGB(fgR, fgG, fgB);
                g_effect.bgColor = CRGB(bgR, bgG, bgB);
                g_effect.period10ms = period > 0 ? period : 10;
                g_effect.durationMs = durMs;
                g_effect.startMs = millis();
                g_effect.toggle = false;
                g_effect.lastToggleMs = 0;
                g_effect.active = true;

                // App effect codes: 0=OFF, 1=ON, 2=BLINK, 3=BREATH, 4=STROBE
                switch (fxType) {
                    case 0: g_effect.anim = EFX_OFF;    break;
                    case 1: g_effect.anim = EFX_ON;     break;
                    case 2: g_effect.anim = EFX_BLINK;  break;
                    case 3: g_effect.anim = EFX_BREATH; break;
                    case 4: g_effect.anim = EFX_STROBE; break;
                    default: g_effect.anim = EFX_ON;    break;
                }

                Serial.printf("  EFX: mode=%d type=%d fg=(%d,%d,%d) period=%d dur=%d\n",
                              mode, fxType, fgR, fgG, fgB, period, durMs);
            } else if (mode == 5) {
                Serial.println("  GAME mode (ignored)");
            }
        }
    }
    void onRead(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo) override {
        g_readFlag = 1;
    }
};

class LoggingCallbacks : public NimBLECharacteristicCallbacks {
    const char* tag;
public:
    LoggingCallbacks(const char* t) : tag(t) {}
    void onRead(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo) override {
        g_readFlag = 1;
    }
    void onWrite(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo) override {
        g_writeFlag = 1;
        std::string data = pChar->getValue();
        Serial.printf("[%lu] [%s WRITE] len=%d: ", millis(), tag, (int)data.length());
        for (size_t i = 0; i < data.length(); i++) Serial.printf("%02X ", (uint8_t)data[i]);
        Serial.println();
    }
};

class FwCharCallbacks : public NimBLECharacteristicCallbacks {
public:
    void onRead(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo) override {
        g_readFlag = 1;
        pChar->setValue(g_fwString);
    }
};

class MacCharCallbacks : public NimBLECharacteristicCallbacks {
    void onRead(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo) override {
        g_readFlag = 1;
        uint8_t mac[6] = {0};
        esp_read_mac(mac, ESP_MAC_BT);
        uint8_t reversed[6] = { mac[5], mac[4], mac[3], mac[2], mac[1], mac[0] };
        pChar->setValue(reversed, 6);
    }
};

class BatteryCallbacks : public NimBLECharacteristicCallbacks {
public:
    void onRead(NimBLECharacteristic* pChar, NimBLEConnInfo& connInfo) override {
        g_readFlag = 1;
        uint8_t level = 99;  // real V4 reports 99%
        pChar->setValue(&level, 1);
    }
};

class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo) override {
        bleConnected = true;
        connHandle = connInfo.getConnHandle();
        pendingDisconnect = false;
        Serial.printf("[%lu] Connected (latched=%d, handle=%d)\n", millis(), latched, connHandle);
        if (latched) {
            leds[0] = pendingColor;
            FastLED.show();
        } else {
            leds[0] = CRGB(0, 0, 255);
            FastLED.show();
        }
    }
    void onDisconnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo, int reason) override {
        bleConnected = false;
        pendingDisconnect = false;
        connHandle = 0;
        Serial.printf("[%lu] Disconnected (reason=%d, latched=%d)\n", millis(), reason, latched);
        if (latched) {
            leds[0] = pendingColor;
            FastLED.show();
        }
        NimBLEDevice::startAdvertising();
    }
};

void flashLED(CRGB color, int times, int delayMs) {
    for (int i = 0; i < times; i++) {
        leds[0] = color;
        FastLED.show();
        delay(delayMs);
        leds[0] = CRGB::Black;
        FastLED.show();
        if (i < times - 1) delay(delayMs);
    }
}

void setup() {
    FastLED.addLeds<WS2812B, LED_PIN, GRB>(leds, NUM_LEDS);
    FastLED.setBrightness(64);
    leds[0] = CRGB::Black;
    FastLED.show();

    Serial.begin(115200);
    delay(500);
    Serial.println();
    Serial.println("=== Army Bomb V4 Spoofer ===");

    esp_err_t macErr = esp_base_mac_addr_set(spoofedMac);
    Serial.printf("Set base MAC: %d\n", macErr);

    NimBLEDevice::init(DEVICE_NAME);
    NimBLEDevice::setMTU(247);

    uint8_t actualMac[6] = {0};
    esp_read_mac(actualMac, ESP_MAC_BT);
    Serial.printf("BLE MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
                  actualMac[0], actualMac[1], actualMac[2],
                  actualMac[3], actualMac[4], actualMac[5]);

    // Build firmware string with actual BLE MAC (matches real V4 format)
    snprintf(g_fwString, sizeof(g_fwString), "1.1 %02X:%02X:%02X:%02X:%02X:%02X 0000 01",
             actualMac[0], actualMac[1], actualMac[2],
             actualMac[3], actualMac[4], actualMac[5]);
    Serial.printf("FW string: %s\n", g_fwString);

    // Reversed MAC for ff05 and 0x2901 descriptor
    uint8_t reversedMac[6] = { actualMac[5], actualMac[4], actualMac[3],
                               actualMac[2], actualMac[1], actualMac[0] };

    pServer = NimBLEDevice::createServer();
    pServer->setCallbacks(new ServerCallbacks());

    // --- Service fe01: color (ff01) + effects (ff02) ---
    NimBLEService* pSvcFe01 = pServer->createService(SVC_FE01_UUID);

    NimBLECharacteristic* pChrFF01 = pSvcFe01->createCharacteristic(
        CHR_FF01_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE
    );
    pChrFF01->setCallbacks(new ColorCharCallbacks());
    uint8_t initFF01[4] = { 0xFF, 0xFF, 0xFF, 0x00 };  // real V4: white
    pChrFF01->setValue(initFF01, 4);

    NimBLECharacteristic* pChrFF02 = pSvcFe01->createCharacteristic(
        CHR_FF02_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE
    );
    pChrFF02->setCallbacks(new EffectsCharCallbacks());
    uint8_t initFF02[4] = { 0x03, 0x00, 0x00, 0x00 };  // real V4: 03-00-00-00
    pChrFF02->setValue(initFF02, 4);

    // --- Service fe06: commit (ff13) + OTA descriptor ---
    NimBLEService* pSvcFe06 = pServer->createService(SVC_FE06_UUID);
    NimBLECharacteristic* pChrFF13 = pSvcFe06->createCharacteristic(
        CHR_FF13_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE_NR
    );
    pChrFF13->setCallbacks(new CommitCharCallbacks());
    uint8_t initFF13 = 0x00;  // real V4: 00
    pChrFF13->setValue(&initFF13, 1);
    NimBLEDescriptor* pDescOta = pChrFF13->createDescriptor(
        "2901", NIMBLE_PROPERTY::READ
    );
    pDescOta->setValue("OTA");  // real V4 descriptor says "OTA"

    // --- Service fe02: ff04 ---
    NimBLEService* pSvcFe02 = pServer->createService(SVC_FE02_UUID);
    NimBLECharacteristic* pChrFF04 = pSvcFe02->createCharacteristic(
        CHR_FF04_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE_NR
    );
    pChrFF04->setCallbacks(new LoggingCallbacks("ff04"));
    uint8_t initFF04[2] = { 0x00, 0x00 };  // real V4: 00-00 (2 bytes)
    pChrFF04->setValue(initFF04, 2);

    // --- Service fe03: ff05 (MAC, reversed) ---
    NimBLEService* pSvcFe03 = pServer->createService(SVC_FE03_UUID);
    NimBLECharacteristic* pChrFF05 = pSvcFe03->createCharacteristic(
        CHR_FF05_UUID, NIMBLE_PROPERTY::READ
    );
    pChrFF05->setValue(reversedMac, 6);
    pChrFF05->setCallbacks(new MacCharCallbacks());

    // --- Service fe04: ff06 ---
    NimBLEService* pSvcFe04 = pServer->createService(SVC_FE04_UUID);
    NimBLECharacteristic* pChrFF06 = pSvcFe04->createCharacteristic(
        CHR_FF06_UUID, NIMBLE_PROPERTY::READ
    );
    pChrFF06->setCallbacks(new LoggingCallbacks("ff06"));
    uint8_t initFF06[2] = { 0x00, 0x00 };  // real V4: 00-00 (2 bytes)
    pChrFF06->setValue(initFF06, 2);

    // --- Device Information Service (0x180A) ---
    NimBLEService* pDevInfo = pServer->createService("180A");

    // 2A29 — Manufacturer Name
    NimBLECharacteristic* pManuf = pDevInfo->createCharacteristic("2A29", NIMBLE_PROPERTY::READ);
    pManuf->setValue("Elcomtec");

    // 2A24 — Model Number (real V4: "BTSNN26JOS900NNO")
    NimBLECharacteristic* pModel = pDevInfo->createCharacteristic("2A24", NIMBLE_PROPERTY::READ);
    pModel->setValue("BTSNN26JOS900NNO");

    // 2A26 — Firmware Revision (dynamic: "1.1 <MAC> 0000 01")
    NimBLECharacteristic* pFirmware = pDevInfo->createCharacteristic("2A26", NIMBLE_PROPERTY::READ);
    pFirmware->setValue(g_fwString);
    pFirmware->setCallbacks(new FwCharCallbacks());

    // 2A00 — Device Name (real V4: "BTS OFFICIAL LIGHT STICK VER.4")
    NimBLECharacteristic* pDevName = pDevInfo->createCharacteristic("2A00", NIMBLE_PROPERTY::READ);
    pDevName->setValue("BTS OFFICIAL LIGHT STICK VER.4");

    // 0x2901 descriptor on 2A00 — stores reversed MAC (real V4 quirk)
    NimBLEDescriptor* pDisDesc2901 = pDevName->createDescriptor("2901", NIMBLE_PROPERTY::READ);
    pDisDesc2901->setValue(reversedMac, 6);

    // 0x2902 descriptor on 2A00 — CCCD stub (real V4 has 00-00)
    NimBLEDescriptor* pDisDesc2902 = pDevName->createDescriptor("2902", NIMBLE_PROPERTY::READ);
    uint8_t cccdVal[2] = { 0x00, 0x00 };
    pDisDesc2902->setValue(cccdVal, 2);

    // --- Battery Service (0x180F) ---
    NimBLEService* pBattery = pServer->createService("180F");
    NimBLECharacteristic* pBattLevel = pBattery->createCharacteristic(
        "2A19", NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY
    );
    uint8_t battLevel = 99;  // real V4: 99%
    pBattLevel->setValue(&battLevel, 1);
    pBattLevel->setCallbacks(new BatteryCallbacks());

    // --- Advertising (name only, no service UUID) ---
    NimBLEAdvertising* pAdvertising = NimBLEDevice::getAdvertising();
    pAdvertising->setName(DEVICE_NAME);
    pAdvertising->enableScanResponse(true);

    bool advOK = NimBLEDevice::startAdvertising();
    if (advOK) {
        Serial.println("Advertising started OK");
        flashLED(CRGB::Green, 2, 150);
    } else {
        Serial.println("ERROR: Failed to start advertising!");
        flashLED(CRGB::Red, 3, 200);
    }
}

void loop() {
    if (g_readFlag) {
        g_readFlag = 0;
        Serial.printf("[%lu] *** onRead fired!\n", millis());
    }
    if (g_writeFlag) {
        g_writeFlag = 0;
        Serial.printf("[%lu] *** onWrite fired!\n", millis());
    }

    // Concert-mode effect animation
    if (g_effect.active && bleConnected) {
        unsigned long now = millis();

        // Check duration expiry
        if (g_effect.durationMs > 0 && now - g_effect.startMs >= g_effect.durationMs) {
            g_effect.active = false;
            leds[0] = CRGB::Black;
            FastLED.show();
        } else {
            unsigned long elapsed = now - g_effect.startMs;
            unsigned long periodMs = (unsigned long)g_effect.period10ms * 10;

            switch (g_effect.anim) {
                case EFX_ON:
                    leds[0] = g_effect.fgColor;
                    break;

                case EFX_OFF:
                    leds[0] = CRGB::Black;
                    break;

                case EFX_STROBE:
                case EFX_BLINK:
                    if (now - g_effect.lastToggleMs >= periodMs) {
                        g_effect.lastToggleMs = now;
                        g_effect.toggle = !g_effect.toggle;
                    }
                    leds[0] = g_effect.toggle ? g_effect.fgColor : g_effect.bgColor;
                    break;

                case EFX_BREATH: {
                    // Sine-wave: fade between bg and fg over one period
                    float phase = (float)(elapsed % periodMs) / (float)periodMs;
                    if (phase > 1.0f) phase = 1.0f;
                    float sinVal = (sinf(phase * 2.0f * 3.14159f) + 1.0f) / 2.0f;  // 0..1
                    CRGB c;
                    c.r = g_effect.bgColor.r + (g_effect.fgColor.r - g_effect.bgColor.r) * sinVal;
                    c.g = g_effect.bgColor.g + (g_effect.fgColor.g - g_effect.bgColor.g) * sinVal;
                    c.b = g_effect.bgColor.b + (g_effect.fgColor.b - g_effect.bgColor.b) * sinVal;
                    leds[0] = c;
                    break;
                }

                default: break;
            }
            FastLED.show();
        }
    }

    if (pendingDisconnect && millis() >= disconnectTarget) {
        if (pServer) {
            pServer->disconnect(connHandle);
        }
        pendingDisconnect = false;
    }

    if (!bleConnected) {
        static unsigned long lastFlashMs = 0;
        static bool flashState = false;
        unsigned long now = millis();

        if (!latched) {
            if (now - lastFlashMs >= 500) {
                lastFlashMs = now;
                flashState = !flashState;
                leds[0] = flashState ? CRGB(0, 0, 255) : CRGB::Black;
                FastLED.show();
            }
        } else {
            leds[0] = pendingColor;
            FastLED.show();
        }
    }

    delay(10);
}

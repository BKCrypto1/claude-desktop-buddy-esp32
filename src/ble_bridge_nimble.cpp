#include "ble_bridge.h"
#include <NimBLEDevice.h>
#include <Arduino.h>
#include <string.h>

// Nordic UART Service UUIDs — every BLE serial example uses these, so
// existing tools (nRF Connect, bluefy, Web Bluetooth examples) can talk to
// us without custom UUIDs.
#define NUS_SERVICE_UUID "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define NUS_RX_UUID      "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
#define NUS_TX_UUID      "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

// Incoming bytes are buffered in a simple ring for bleRead()/bleAvailable().
static const size_t RX_CAP = 2048;
static uint8_t  rxBuf[RX_CAP];
static volatile size_t rxHead = 0;
static volatile size_t rxTail = 0;

static NimBLEServer*         server = nullptr;
static NimBLECharacteristic* txChar = nullptr;
static NimBLECharacteristic* rxChar = nullptr;
static volatile bool      connected = false;
static volatile bool      secure = false;
static volatile uint32_t  passkey = 0;
static volatile uint16_t  mtu = 23;

static void rxPush(const uint8_t* p, size_t n) {
  for (size_t i = 0; i < n; i++) {
    size_t next = (rxHead + 1) % RX_CAP;
    if (next == rxTail) return;  // full — drop (upstream should keep up)
    rxBuf[rxHead] = p[i];
    rxHead = next;
  }
}

class RxCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* c, NimBLEConnInfo&) override {
    std::string v = c->getValue();
    if (v.size() > 0) rxPush((const uint8_t*)v.data(), v.size());
  }
};

// In NimBLE 2.x, connection + pairing callbacks are all on NimBLEServerCallbacks.
class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer*, NimBLEConnInfo&) override {
    connected = true;
    Serial.println("[ble] connected");
  }
  void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int reason) override {
    connected = false;
    secure   = false;
    passkey  = 0;
    mtu      = 23;
    Serial.printf("[ble] disconnected reason=%d\n", reason);
    // Restart advertising so the next client can find us.
    NimBLEDevice::startAdvertising();
  }
  void onMTUChange(uint16_t newMtu, NimBLEConnInfo&) override {
    mtu = newMtu;
    Serial.printf("[ble] mtu=%u\n", mtu);
  }
  // LE Secure Connections, DisplayOnly IO capability: the stack calls
  // onPassKeyDisplay to get a 6-digit code to show; user types it on the
  // desktop to complete bonding. main.cpp polls blePasskey() to render it.
  uint32_t onPassKeyDisplay() override {
    passkey = (uint32_t)random(100000, 999999);
    Serial.printf("[ble] passkey %06lu\n", (unsigned long)passkey);
    return passkey;
  }
  void onAuthenticationComplete(NimBLEConnInfo& connInfo) override {
    passkey = 0;
    secure  = connInfo.isEncrypted();
    Serial.printf("[ble] auth %s\n", secure ? "ok" : "FAIL");
    if (!secure && server) server->disconnect(connInfo.getConnHandle());
  }
};

void bleInit(const char* deviceName) {
  NimBLEDevice::init(deviceName);
  // Request the biggest MTU we can get. macOS negotiates to 185 typically.
  NimBLEDevice::setMTU(517);

  // LE Secure Connections + MITM + bonding; device is DisplayOnly.
  NimBLEDevice::setSecurityAuth(true, true, true);
  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_ONLY);

  server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  NimBLEService* svc = server->createService(NUS_SERVICE_UUID);

  txChar = svc->createCharacteristic(
    NUS_TX_UUID,
    NIMBLE_PROPERTY::NOTIFY | NIMBLE_PROPERTY::READ_ENC);

  rxChar = svc->createCharacteristic(
    NUS_RX_UUID,
    NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR | NIMBLE_PROPERTY::WRITE_ENC);
  rxChar->setCallbacks(new RxCallbacks());

  // svc->start() removed: NimBLE 2.x auto-starts services with the server.

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  // BLE legacy advertisement is limited to 31 bytes of payload. A 128-bit
  // UUID is 18 bytes on the wire (2 header + 16 UUID), the name "Claude-XXXX"
  // is 13 bytes, flags are 3 — together that's 34 bytes, over budget. Split
  // across the two packets: flags + name in the main adv (so scanners see
  // the name immediately), 128-bit UUID in the scan response.
  NimBLEAdvertisementData advData;
  advData.setFlags(BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP);
  advData.setName(deviceName);
  adv->setAdvertisementData(advData);

  NimBLEAdvertisementData scanRsp;
  scanRsp.addServiceUUID(NUS_SERVICE_UUID);
  adv->setScanResponseData(scanRsp);

  adv->setPreferredParams(0x06, 0x12);   // iOS-friendly connection interval

  // Faster advertising interval for easier discovery (default is slow).
  // 0x20 = 32 * 0.625 ms = 20 ms min; 0x40 = 40 ms max.
  adv->setMinInterval(0x20);
  adv->setMaxInterval(0x40);

  NimBLEDevice::setPower(9);

  NimBLEDevice::startAdvertising();
  Serial.printf("[ble] advertising as '%s'\n", deviceName);
}

bool bleConnected() { return connected; }
bool bleSecure()    { return secure; }
uint32_t blePasskey() { return passkey; }

void bleClearBonds() {
  int n = NimBLEDevice::getNumBonds();
  if (n > 0) NimBLEDevice::deleteAllBonds();
  Serial.printf("[ble] cleared %d bond(s)\n", n);
}

size_t bleAvailable() {
  return (rxHead + RX_CAP - rxTail) % RX_CAP;
}

int bleRead() {
  if (rxHead == rxTail) return -1;
  int b = rxBuf[rxTail];
  rxTail = (rxTail + 1) % RX_CAP;
  return b;
}

size_t bleWrite(const uint8_t* data, size_t len) {
  if (!connected || !txChar) return 0;
  // ATT notify payload is limited to (MTU - 3). macOS negotiates 185, so
  // the 182-byte chunk works there; use the live mtu so a peer that caps
  // at the 23-byte default doesn't get truncated notifies.
  size_t chunk = mtu > 3 ? mtu - 3 : 20;
  if (chunk > 180) chunk = 180;
  size_t sent = 0;
  while (sent < len) {
    size_t n = len - sent;
    if (n > chunk) n = chunk;
    txChar->setValue((uint8_t*)(data + sent), n);
    txChar->notify();
    sent += n;
    delay(4);
  }
  return sent;
}

#include "ble_link.h"

#include <NimBLEDevice.h>

#include "config.h"

namespace ble_link {

namespace {
NimBLEServer* g_server = nullptr;
NimBLECharacteristic* g_status = nullptr;
NimBLECharacteristic* g_event = nullptr;
CommandHandler g_handler = nullptr;

class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* server, ble_gap_conn_desc* desc) override {
    // Ask for a relaxed connection interval: plenty for commands, gentle on the battery.
    server->updateConnParams(desc->conn_handle, 80, 160, 0, 400);
  }
  void onDisconnect(NimBLEServer*) override { NimBLEDevice::startAdvertising(); }
};

class CommandCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* c) override {
    std::string v = c->getValue();
    if (g_handler && !v.empty()) g_handler(v.data(), v.size());
  }
};

ServerCallbacks g_serverCallbacks;
CommandCallbacks g_commandCallbacks;
}  // namespace

void begin(const char* name, unsigned passkey, CommandHandler onCommand) {
  g_handler = onCommand;
  NimBLEDevice::init(name);
  NimBLEDevice::setPower(ESP_PWR_LVL_P3);
  NimBLEDevice::setMTU(517);                                 // status JSON fits one notification
  NimBLEDevice::setSecurityAuth(true, true, true);           // bond, MITM protection, LE secure connections
  NimBLEDevice::setSecurityPasskey(passkey);
  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_ONLY);    // the phone types the passkey in

  g_server = NimBLEDevice::createServer();
  g_server->setCallbacks(&g_serverCallbacks, false);
  NimBLEService* svc = g_server->createService(BLE_SERVICE_UUID);
  NimBLECharacteristic* cmd = svc->createCharacteristic(
      BLE_COMMAND_UUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_ENC | NIMBLE_PROPERTY::WRITE_AUTHEN);
  cmd->setCallbacks(&g_commandCallbacks);
  g_status = svc->createCharacteristic(
      BLE_STATUS_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::READ_ENC | NIMBLE_PROPERTY::NOTIFY);
  g_event = svc->createCharacteristic(BLE_EVENT_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::READ_ENC |
                                                          NIMBLE_PROPERTY::NOTIFY);
  svc->start();

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  adv->addServiceUUID(BLE_SERVICE_UUID);
  adv->setScanResponse(true);
  adv->setMinInterval(800);    // 0.5-1 s advertising interval (units of 0.625 ms)
  adv->setMaxInterval(1600);
  adv->start();
}

bool connected() { return g_server && g_server->getConnectedCount() > 0; }

void sendStatus(const char* json, size_t len) {
  if (!g_status) return;
  g_status->setValue(reinterpret_cast<const uint8_t*>(json), len);
  if (connected()) g_status->notify();
}

void sendEvent(const char* json, size_t len) {
  if (!g_event) return;
  g_event->setValue(reinterpret_cast<const uint8_t*>(json), len);
  if (connected()) g_event->notify();
}

void stop() { NimBLEDevice::deinit(true); }

}  // namespace ble_link

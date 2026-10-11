// Bluetooth LE link to the phone: one write characteristic for commands and two
// notify characteristics for status and events. Pairing needs the passkey in
// config.h, and every characteristic requires an encrypted (paired) link.
#pragma once
#include <cstddef>

namespace ble_link {

using CommandHandler = void (*)(const char* text, size_t len);

void begin(const char* name, unsigned passkey, CommandHandler onCommand);
bool connected();
void sendStatus(const char* json, size_t len);
void sendEvent(const char* json, size_t len);
void stop();   // before deep sleep

}  // namespace ble_link

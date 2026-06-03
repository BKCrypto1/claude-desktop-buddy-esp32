#pragma once
#include <cstdint>
typedef int esp_mac_type_t;
#define ESP_MAC_BT 1
inline int esp_read_mac(uint8_t* out, esp_mac_type_t /*t*/) {
  static const uint8_t fake[6] = { 0xC0, 0xDE, 0x51, 0x4D, 0xBE, 0xEF };
  for (int i = 0; i < 6; i++) out[i] = fake[i];
  return 0;
}

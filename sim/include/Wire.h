#pragma once
#include <Arduino.h>
class TwoWire {
public:
  bool begin(int /*sda*/ = -1, int /*scl*/ = -1) { return true; }
  bool setClock(uint32_t /*hz*/)                  { return true; }
  void beginTransmission(uint8_t)                 {}
  uint8_t endTransmission(bool /*stop*/ = true)   { return 0; }
  size_t write(uint8_t)                           { return 1; }
  size_t write(const uint8_t*, size_t n)          { return n; }
  uint8_t requestFrom(uint8_t, uint8_t n, bool /*stop*/ = true) { return n; }
  int available()                                  { return 0; }
  int read()                                       { return 0; }
};
extern TwoWire Wire;

#include <Arduino.h>
#include <Wire.h>
#include <chrono>
#include <thread>
#include <cstdarg>
#include <cstdio>

// ──────────────── time ────────────────

static auto _t0 = std::chrono::steady_clock::now();

uint32_t millis() {
  auto now = std::chrono::steady_clock::now();
  return (uint32_t)std::chrono::duration_cast<std::chrono::milliseconds>(now - _t0).count();
}

uint32_t micros() {
  auto now = std::chrono::steady_clock::now();
  return (uint32_t)std::chrono::duration_cast<std::chrono::microseconds>(now - _t0).count();
}

void delay(uint32_t ms) {
  std::this_thread::sleep_for(std::chrono::milliseconds(ms));
}

void delayMicroseconds(uint32_t us) {
  std::this_thread::sleep_for(std::chrono::microseconds(us));
}

// ──────────────── Serial: writes go to stdout, reads come from a USB-pipe shim ────────────────
// The firmware's data.h drains _usbLine.feed(Serial, ...) — for the simulator
// this is a no-op (no host-side stdin scenario player wired up here). The
// BLE bridge stub feeds JSON via the bleAvailable/bleRead path instead.

HardwareSerial Serial;

int    HardwareSerial::available()    { return 0; }
int    HardwareSerial::read()         { return -1; }
int    HardwareSerial::peek()         { return -1; }
size_t HardwareSerial::write(uint8_t b) {
  std::fputc(b, stdout); std::fflush(stdout); return 1;
}
size_t HardwareSerial::write(const uint8_t* buf, size_t len) {
  size_t n = std::fwrite(buf, 1, len, stdout); std::fflush(stdout); return n;
}
size_t HardwareSerial::printf(const char* fmt, ...) {
  char buf[512];
  va_list ap; va_start(ap, fmt);
  int n = std::vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  if (n < 0) return 0;
  return write((const uint8_t*)buf, (size_t)n);
}

// ──────────────── ESP ────────────────

_ESPClass ESP;

uint32_t _ESPClass::getFreeHeap() const { return 200000; }   // arbitrary plausible value
void     _ESPClass::restart() {
  Serial.println("ESP.restart() — exiting simulator");
  std::exit(0);
}

// ──────────────── Wire (no-op singleton) ────────────────

TwoWire Wire;

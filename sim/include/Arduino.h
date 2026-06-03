#pragma once
// Minimal Arduino.h shim for the desktop simulator.
// Only what main.cpp / data.h / xfer.h / stats.h / buddy.cpp / character.cpp
// actually consume. Real Arduino has tons more — we add as needed.

#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <esp_random.h>   // firmware uses esp_random() in data.h without explicit include

// Arduino's "byte" alias (some ArduinoJson versions reference it).
typedef uint8_t byte;

uint32_t millis();
uint32_t micros();
void     delay(uint32_t ms);
void     delayMicroseconds(uint32_t us);

// Pin-mode no-ops so any stray firmware code that pokes a GPIO links.
#define INPUT          0
#define INPUT_PULLUP   1
#define OUTPUT         2
#define HIGH           1
#define LOW            0
inline void  pinMode(int, int)        {}
inline void  digitalWrite(int, int)   {}
inline int   digitalRead(int)         { return 0; }
inline int   analogRead(int)          { return 0; }
inline void  analogWrite(int, int)    {}

// Stream / Serial — line-buffered stdout, byte-at-a-time stdin.
class Stream {
public:
  virtual ~Stream() = default;
  virtual int available()    = 0;
  virtual int read()         = 0;
  virtual int peek()         = 0;
  virtual size_t write(uint8_t) = 0;
  virtual size_t write(const uint8_t* buf, size_t len) {
    for (size_t i = 0; i < len; i++) write(buf[i]);
    return len;
  }
};

class HardwareSerial : public Stream {
public:
  void   begin(unsigned long /*baud*/) {}
  void   end()                         {}
  int    available() override;
  int    read()      override;
  int    peek()      override;
  size_t write(uint8_t b) override;
  size_t write(const uint8_t* buf, size_t len) override;
  size_t write(const char* s) { return write((const uint8_t*)s, std::strlen(s)); }
  size_t write(const char* s, size_t len) { return write((const uint8_t*)s, len); }
  size_t print(const char* s) { return write(s); }
  size_t print(int v)         { char b[16]; int n = snprintf(b, sizeof(b), "%d", v); return write((const uint8_t*)b, n); }
  size_t println(const char* s) { size_t n = write(s); n += write((const uint8_t*)"\n", 1); return n; }
  size_t println()              { return write((const uint8_t*)"\n", 1); }
  size_t printf(const char* fmt, ...);
  void   flush() {}
  operator bool() const { return true; }
};
extern HardwareSerial Serial;

// Arduino's String — only the trivially-used surface (toString of int, c_str).
class String {
  std::string s;
public:
  String() = default;
  String(const char* c) : s(c ? c : "") {}
  String(int v)         { char b[16]; snprintf(b, sizeof(b), "%d", v); s = b; }
  const char* c_str() const { return s.c_str(); }
  size_t length() const     { return s.length(); }
  String operator+(const String& o) const { String r = *this; r.s += o.s; return r; }
  String& operator+=(const String& o) { s += o.s; return *this; }
};

// ESP namespace — only getFreeHeap and restart are referenced.
struct _ESPClass {
  uint32_t getFreeHeap() const;
  void     restart();
};
extern _ESPClass ESP;

// FreeRTOS-style yield (unused under SIM_HOST but referenced in some headers).
inline void yield() {}
inline void taskYIELD() {}

// PSRAM allocator stubs — MALLOC_CAP_SPIRAM gets ignored, plain malloc.
#define MALLOC_CAP_SPIRAM 0x00000400
#define MALLOC_CAP_8BIT   0x00000004
#define MALLOC_CAP_DMA    0x00000008
inline void* heap_caps_malloc(size_t n, uint32_t /*caps*/) { return std::malloc(n); }
inline void  heap_caps_free(void* p)                       { std::free(p); }

// Small helpers a couple of headers reach for.
#ifndef min
template<typename A, typename B> auto min(A a, B b) -> decltype(a < b ? a : b) { return a < b ? a : b; }
#endif
#ifndef max
template<typename A, typename B> auto max(A a, B b) -> decltype(a > b ? a : b) { return a > b ? a : b; }
#endif

#pragma once
#include <Arduino.h>
#include <string>

class Preferences {
public:
  bool   begin(const char* ns, bool readOnly = false);
  void   end();
  bool   clear();
  size_t putUInt   (const char* key, uint32_t v);
  size_t putUShort (const char* key, uint16_t v);
  size_t putUChar  (const char* key, uint8_t  v);
  size_t putBool   (const char* key, bool     v);
  size_t putString (const char* key, const char* v);
  size_t putBytes  (const char* key, const void* v, size_t n);
  uint32_t getUInt   (const char* key, uint32_t def = 0);
  uint16_t getUShort (const char* key, uint16_t def = 0);
  uint8_t  getUChar  (const char* key, uint8_t  def = 0);
  bool     getBool   (const char* key, bool     def = false);
  size_t   getString (const char* key, char* buf, size_t n);
  size_t   getBytes  (const char* key, void*  buf, size_t n);
  bool     isKey     (const char* key);
};

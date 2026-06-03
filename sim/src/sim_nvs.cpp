// Preferences shim — persists NVS keys to ~/.cache/buddy-sim/nvs.json.
// Keeps parity with ESP32 Preferences semantics (per-namespace, typed
// getters/putters with default fallback).

#include <Preferences.h>
#include <ArduinoJson.h>
#include <LittleFS.h>
#include <fstream>
#include <sstream>
#include <cstdlib>
#include <string>
#include <sys/stat.h>

namespace {
struct Store {
  JsonDocument doc;
  std::string  path;
  bool         loaded = false;

  void ensureLoaded() {
    if (loaded) return;
    const char* h = std::getenv("HOME");
    std::string dir = std::string(h ? h : "/tmp") + "/.cache/buddy-sim";
    ::mkdir(dir.c_str(), 0755);
    path = dir + "/nvs.json";
    std::ifstream in(path);
    if (in) {
      std::stringstream ss; ss << in.rdbuf();
      deserializeJson(doc, ss.str());
    }
    loaded = true;
  }
  void save() {
    std::ofstream out(path, std::ios::trunc);
    serializeJson(doc, out);
  }
};
Store s_store;

JsonObject ns(const char* n) {
  s_store.ensureLoaded();
  if (!s_store.doc[n].is<JsonObject>()) s_store.doc[n].to<JsonObject>();
  return s_store.doc[n].as<JsonObject>();
}
}

struct PrefsImpl {
  std::string nsName;
  bool        readOnly = false;
};

// Hide the impl behind a static map — Preferences is small, only one or two
// instances exist at a time, so we just store the namespace inside the class
// via a side-store keyed by `this`. Simpler: stash it in a single global,
// since the firmware uses a fresh Preferences in each begin/end cycle.
static std::string s_currentNs;

bool Preferences::begin(const char* n, bool /*readOnly*/) {
  s_currentNs = n ? n : "";
  s_store.ensureLoaded();
  return true;
}

void Preferences::end() {
  s_store.save();
  s_currentNs.clear();
}

bool Preferences::clear() {
  if (s_currentNs.empty()) return false;
  s_store.doc.remove(s_currentNs);
  s_store.save();
  return true;
}

#define NS() ns(s_currentNs.c_str())

size_t Preferences::putUInt(const char* k, uint32_t v)   { NS()[k] = v; s_store.save(); return 4; }
size_t Preferences::putUShort(const char* k, uint16_t v) { NS()[k] = v; s_store.save(); return 2; }
size_t Preferences::putUChar(const char* k, uint8_t v)   { NS()[k] = v; s_store.save(); return 1; }
size_t Preferences::putBool(const char* k, bool v)       { NS()[k] = v; s_store.save(); return 1; }
size_t Preferences::putString(const char* k, const char* v) { NS()[k] = v ? v : ""; s_store.save(); return v ? std::strlen(v) : 0; }
size_t Preferences::putBytes(const char* k, const void* v, size_t n) {
  // Encode as base64 so JSON stays text-safe.
  std::string b;
  static const char* T = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const uint8_t* p = (const uint8_t*)v;
  for (size_t i = 0; i < n; i += 3) {
    uint32_t x = p[i] << 16 | (i+1<n?p[i+1]:0) << 8 | (i+2<n?p[i+2]:0);
    b += T[(x>>18)&63]; b += T[(x>>12)&63];
    b += (i+1<n) ? T[(x>>6)&63] : '=';
    b += (i+2<n) ? T[x&63] : '=';
  }
  NS()[k] = b;
  s_store.save();
  return n;
}

uint32_t Preferences::getUInt(const char* k, uint32_t d)   { auto v = NS()[k]; return v.is<uint32_t>() ? v.as<uint32_t>() : d; }
uint16_t Preferences::getUShort(const char* k, uint16_t d) { auto v = NS()[k]; return v.is<uint16_t>() ? v.as<uint16_t>() : d; }
uint8_t  Preferences::getUChar(const char* k, uint8_t d)   { auto v = NS()[k]; return v.is<uint8_t>()  ? v.as<uint8_t>()  : d; }
bool     Preferences::getBool(const char* k, bool d)       { auto v = NS()[k]; return v.is<bool>()     ? v.as<bool>()     : d; }
size_t   Preferences::getString(const char* k, char* buf, size_t n) {
  auto v = NS()[k];
  if (!v.is<const char*>() || !buf || n == 0) return 0;
  const char* s = v.as<const char*>();
  size_t len = std::strlen(s);
  if (len + 1 > n) len = n - 1;
  std::memcpy(buf, s, len);
  buf[len] = 0;
  return len;
}
size_t Preferences::getBytes(const char* k, void* buf, size_t n) {
  auto v = NS()[k];
  if (!v.is<const char*>() || !buf) return 0;
  const char* s = v.as<const char*>();
  size_t slen = std::strlen(s);
  size_t out = 0;
  auto b64 = [](char c) -> int {
    if (c>='A'&&c<='Z') return c-'A';
    if (c>='a'&&c<='z') return c-'a'+26;
    if (c>='0'&&c<='9') return c-'0'+52;
    if (c=='+') return 62; if (c=='/') return 63;
    return -1;
  };
  uint8_t* p = (uint8_t*)buf;
  for (size_t i = 0; i + 3 < slen && out < n; i += 4) {
    int a=b64(s[i]), b=b64(s[i+1]), c=b64(s[i+2]), d=b64(s[i+3]);
    if (a<0||b<0) break;
    if (out < n) p[out++] = (uint8_t)((a<<2) | (b>>4));
    if (c >= 0 && out < n) p[out++] = (uint8_t)((b<<4) | (c>>2));
    if (d >= 0 && out < n) p[out++] = (uint8_t)((c<<6) |  d);
  }
  return out;
}
bool Preferences::isKey(const char* k) {
  return !NS()[k].isNull();
}

#include "hw/rtc.h"
#include <ctime>

static long s_offsetSec = 0;   // applied via hwRtcWrite (e.g., desktop time-sync)

bool hwRtcInit() { return true; }

bool hwRtcRead(HwTime* t) {
  if (!t) return false;
  std::time_t now = std::time(nullptr) + s_offsetSec;
  std::tm lt;
#if defined(_WIN32)
  localtime_s(&lt, &now);
#else
  localtime_r(&now, &lt);
#endif
  t->H  = (uint8_t)lt.tm_hour;
  t->M  = (uint8_t)lt.tm_min;
  t->S  = (uint8_t)lt.tm_sec;
  t->Y  = (uint16_t)(1900 + lt.tm_year);
  t->Mo = (uint8_t)(lt.tm_mon + 1);
  t->D  = (uint8_t)lt.tm_mday;
  t->dow = (uint8_t)lt.tm_wday;
  return true;
}

bool hwRtcWrite(const HwTime& t) {
  std::tm w{};
  w.tm_hour = t.H;
  w.tm_min  = t.M;
  w.tm_sec  = t.S;
  w.tm_year = (int)t.Y - 1900;
  w.tm_mon  = (int)t.Mo - 1;
  w.tm_mday = t.D;
  w.tm_isdst = -1;
  std::time_t target = std::mktime(&w);
  std::time_t now    = std::time(nullptr);
  s_offsetSec = (long)(target - now);
  return true;
}

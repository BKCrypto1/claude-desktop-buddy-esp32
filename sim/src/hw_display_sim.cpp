// Sim replacement for src/hw/display.cpp.
// Owns a 184×224 RGB565 canvas; on push, hands the canvas to sim_panel
// which runs the same letterbox+rotate pipeline as the real device.

#include "hw/display.h"
#include <Arduino.h>
#include "sim_panel.h"

static Arduino_Canvas* s_canvas = nullptr;
static uint8_t s_brightness = 200;
static bool    s_displayOn  = true;
static bool    s_borderAlertOn = false;

extern "C" void hwBorderAlertSetInternal(bool on);
void hwBorderAlertSetInternal(bool on) { s_borderAlertOn = on; }

bool hwDisplayInit() {
  if (!s_canvas) {
    s_canvas = new Arduino_Canvas(HW_W, HW_H, nullptr);
    if (!s_canvas->begin()) return false;
    s_canvas->setUTF8Print(true);
  }
  return true;
}

Arduino_Canvas* hwCanvas() { return s_canvas; }

void hwDisplayBrightness(uint8_t lvl) {
  static const uint8_t LUT[5] = { 50, 100, 150, 200, 255 };
  if (lvl > 4) lvl = 4;
  s_brightness = LUT[lvl];
}

void hwDisplaySleep(bool off) {
  s_displayOn = !off;
  if (off) s_brightness = 0;
  else     hwDisplayBrightness(2);
}

void hwDisplayPush() {
  if (!s_canvas) return;
  uint8_t b = s_displayOn ? s_brightness : 0;
  simPanelPush(s_canvas->getFramebuffer(), b, s_borderAlertOn);
}

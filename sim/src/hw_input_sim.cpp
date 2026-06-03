// Sim replacement for src/hw/input.cpp.
//
// Keyboard maps to physical keys; mouse drag/click maps to touch.
// The board profile (S3 2.16) has BOARD_KEY1_ACTIVE_HIGH=1, BOARD_HAS_KEY2=1,
// BOARD_BTN_THIRD=1 — but we don't reproduce those branches here, we just
// bake in the resulting behaviour:
//   - Space  → BtnA
//   - B      → BtnB
//   - M      → synthesised BtnA long-press (via BOOT key path)
//   - Click  → touch (canvas-space coords from sim_panel)

#include "hw/input.h"
#include <Arduino.h>
#include "sim_panel.h"

static HwBtn   s_a, s_b;
static HwTouch s_tp;
static uint8_t s_axpEvt = 0;
static uint32_t s_bootHeldAt = 0;
static bool    s_lastKey1 = false, s_lastKey2 = false, s_lastBoot = false;

bool HwBtn::pressedFor(uint32_t ms) {
  return isPressed && (millis() - pressedAt) >= ms;
}

bool hwInputInit() { return true; }

static void scanKey1(bool pressed) {
  uint32_t now = millis();
  s_a.wasPressed  = pressed && !s_a.isPressed;
  s_a.wasReleased = !pressed && s_a.isPressed;
  if (s_a.wasPressed) s_a.pressedAt = now;
  s_a.isPressed = pressed;
}

static void scanKey2(bool pressed) {
  uint32_t now = millis();
  s_b.wasPressed  = pressed && !s_b.isPressed;
  s_b.wasReleased = !pressed && s_b.isPressed;
  if (s_b.wasPressed) s_b.pressedAt = now;
  s_b.isPressed = pressed;
}

static void scanBootKey(bool pressed) {
  if (pressed && !s_bootHeldAt) {
    s_bootHeldAt = millis();
  } else if (!pressed && s_bootHeldAt) {
    uint32_t held = millis() - s_bootHeldAt;
    s_bootHeldAt = 0;
    if (held > 30 && held < 1000) {
      s_a.wasPressed  = true;
      s_a.wasReleased = true;
      s_a.pressedAt   = millis() - 1500;
      s_a.isPressed   = false;
    }
  }
}

void hwInputUpdate() {
  const SimKeys& k = simPanelKeys();
  scanKey1(k.key1);
  scanKey2(k.key2);
  scanBootKey(k.keyBoot);

  // Mouse → touch
  SimMouse m = simPanelMouse();
  bool down = m.down && m.valid;
  if (down) {
    s_tp.justPressed  = !s_tp.down;
    s_tp.justReleased = false;
    s_tp.x = m.cx;
    s_tp.y = m.cy;
    s_tp.down = true;
  } else {
    s_tp.justReleased = s_tp.down;
    s_tp.down = false;
    s_tp.justPressed  = false;
  }
}

HwBtn& hwBtnA() { return s_a; }
HwBtn& hwBtnB() { return s_b; }
uint8_t hwAxpBtnEvent() { uint8_t e = s_axpEvt; if (e == 0x04) s_axpEvt = 0; return e; }
const HwTouch& hwTouch() { return s_tp; }
bool hwTouchIrqPending() { return false; }

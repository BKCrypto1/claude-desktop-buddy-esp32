#pragma once
#include <cstdint>

// Initialise SDL2 window + renderer at 480×480. Returns false on SDL failure.
bool simPanelInit(const char* title);

// Push the firmware's 184×224 logical canvas → letterbox to 368×448 →
// rotate 90° CCW (matches MADCTL=0xA0) → blit to the 480×480 SDL window.
// `border_alert` draws the red notification pill above the canvas, same
// coords as src/hw/display.cpp:237-243.
void simPanelPush(const uint16_t* canvas_184x224,
                  uint8_t brightness_0_255,
                  bool border_alert);

void simPanelShutdown();

// Pump SDL events. Returns false when the user closes the window.
bool simPanelPumpEvents();

// Touch / mouse sample for hw_input_sim. Coords are in canvas space
// (0..183 / 0..223). down=true while the left mouse button is held.
struct SimMouse {
  bool    down;
  int16_t cx, cy;       // canvas-space (after reverse letterbox + rotate)
  bool    valid;        // false if the click landed outside the canvas region
};
SimMouse simPanelMouse();

// Keyboard state. Each flag is "is this key currently held" — caller
// debounces and turns into rising/falling edges.
struct SimKeys {
  bool key1;     // PWR / Space
  bool key2;     // IO18 / B
  bool keyBoot;  // BOOT / M
  bool shake;    // S
  bool faceDown; // F (toggle)
  bool usbToggle;// U (rising edge)
};
const SimKeys& simPanelKeys();

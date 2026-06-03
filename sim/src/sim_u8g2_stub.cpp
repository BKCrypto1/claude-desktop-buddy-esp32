// M1 stub for U8g2 path. M2 replaces with the real chill7_h_cjk decoder.
// For now, fall through to the built-in 5x7 font so HUD lines aren't blank.

#include <Arduino_GFX_Library.h>
#include "sim_font_5x7.h"

// Firmware references `u8g2_font_chill7_h_cjk` directly (main.cpp:914).
// In real builds it comes from Arduino_GFX's bundled U8g2 font tables;
// here we just need a single-byte marker so setFont() has something
// non-null to point at — the value is ignored by the stub renderer.
extern "C" const uint8_t u8g2_font_chill7_h_cjk[1] = { 0 };

int simU8g2DrawGlyph(Arduino_GFX* g, const uint8_t* /*font*/,
                     int16_t x, int16_t y, uint32_t cp,
                     uint16_t fg, uint16_t bg, bool bgEnabled) {
  // u8g2 cursor convention is baseline; built-in font is top-left. Subtract
  // a typical 7-px ascent so text doesn't sit one row off until we land the
  // real font.
  char ch = (cp < 128) ? (char)cp : '?';
  for (int8_t col = 0; col < 6; col++) {
    uint8_t bits = (col < 5 && (uint8_t)ch < 128) ? sim_font_5x7[(uint8_t)ch][col] : 0;
    for (int8_t row = 0; row < 8; row++) {
      bool on = bits & (1 << row);
      if (on)               g->drawPixel(x + col, y - 7 + row, fg);
      else if (bgEnabled)   g->drawPixel(x + col, y - 7 + row, bg);
    }
  }
  return 6;
}

int simU8g2GlyphWidth(const uint8_t* /*font*/, uint32_t /*cp*/) { return 6; }

void simU8g2FontMetrics(const uint8_t* /*font*/,
                        int* ascent, int* descent, int* lineHeight) {
  if (ascent)     *ascent     = 7;
  if (descent)    *descent    = 0;
  if (lineHeight) *lineHeight = 10;
}

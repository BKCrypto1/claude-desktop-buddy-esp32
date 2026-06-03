#pragma once
#include <cstdint>
// 5x7 ASCII bitmap font (column-major, 5 columns/glyph, bit 0 = top row).
// Public domain — extracted from Adafruit-GFX-Library/glcdfont.c
// (Bdf2c-style, original by James W. Z. Hauser, used widely as
// "the standard Arduino_GFX/Adafruit_GFX 5x7 font").
extern const uint8_t sim_font_5x7[256][5];

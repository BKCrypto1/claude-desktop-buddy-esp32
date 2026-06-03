#include <Arduino_GFX_Library.h>
#include "sim_font_5x7.h"
#include <cstdarg>
#include <cstring>
#include <cstdlib>

// ──────────────── Arduino_GFX base ────────────────

Arduino_GFX::Arduino_GFX(int16_t w, int16_t h) : _w(w), _h(h) {}
Arduino_GFX::~Arduino_GFX() = default;

void Arduino_GFX::fillScreen(uint16_t color) { fillRect(0, 0, _w, _h, color); }

void Arduino_GFX::drawPixel(int16_t /*x*/, int16_t /*y*/, uint16_t /*c*/) {
  // Base does nothing — Arduino_Canvas overrides.
}

void Arduino_GFX::fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color) {
  for (int16_t j = 0; j < h; j++)
    for (int16_t i = 0; i < w; i++)
      drawPixel(x + i, y + j, color);
}

void Arduino_GFX::drawRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color) {
  drawFastHLine(x,         y,         w, color);
  drawFastHLine(x,         y + h - 1, w, color);
  drawFastVLine(x,         y,         h, color);
  drawFastVLine(x + w - 1, y,         h, color);
}

void Arduino_GFX::drawFastHLine(int16_t x, int16_t y, int16_t w, uint16_t color) {
  for (int16_t i = 0; i < w; i++) drawPixel(x + i, y, color);
}

void Arduino_GFX::drawFastVLine(int16_t x, int16_t y, int16_t h, uint16_t color) {
  for (int16_t j = 0; j < h; j++) drawPixel(x, y + j, color);
}

void Arduino_GFX::drawLine(int16_t x0, int16_t y0, int16_t x1, int16_t y1, uint16_t color) {
  // Bresenham — same as Adafruit_GFX.
  int dx =  std::abs(x1 - x0);
  int dy = -std::abs(y1 - y0);
  int sx = x0 < x1 ? 1 : -1;
  int sy = y0 < y1 ? 1 : -1;
  int err = dx + dy;
  while (true) {
    drawPixel(x0, y0, color);
    if (x0 == x1 && y0 == y1) break;
    int e2 = 2 * err;
    if (e2 >= dy) { err += dy; x0 += sx; }
    if (e2 <= dx) { err += dx; y0 += sy; }
  }
}

// Bresenham circle (same shape as Adafruit_GFX). Draws 4 octants.
void Arduino_GFX::drawCircle(int16_t cx, int16_t cy, int16_t r, uint16_t color) {
  int16_t x = 0, y = r;
  int16_t f = 1 - r, ddF_x = 1, ddF_y = -2 * r;
  drawPixel(cx, cy + r, color); drawPixel(cx, cy - r, color);
  drawPixel(cx + r, cy, color); drawPixel(cx - r, cy, color);
  while (x < y) {
    if (f >= 0) { y--; ddF_y += 2; f += ddF_y; }
    x++; ddF_x += 2; f += ddF_x;
    drawPixel(cx + x, cy + y, color); drawPixel(cx - x, cy + y, color);
    drawPixel(cx + x, cy - y, color); drawPixel(cx - x, cy - y, color);
    drawPixel(cx + y, cy + x, color); drawPixel(cx - y, cy + x, color);
    drawPixel(cx + y, cy - x, color); drawPixel(cx - y, cy - x, color);
  }
}

void Arduino_GFX::fillCircle(int16_t cx, int16_t cy, int16_t r, uint16_t color) {
  // Filled scan-line variant.
  drawFastVLine(cx, cy - r, 2 * r + 1, color);
  int16_t x = 0, y = r;
  int16_t f = 1 - r, ddF_x = 1, ddF_y = -2 * r;
  while (x < y) {
    if (f >= 0) { y--; ddF_y += 2; f += ddF_y; }
    x++; ddF_x += 2; f += ddF_x;
    drawFastVLine(cx + x, cy - y, 2 * y + 1, color);
    drawFastVLine(cx - x, cy - y, 2 * y + 1, color);
    drawFastVLine(cx + y, cy - x, 2 * x + 1, color);
    drawFastVLine(cx - y, cy - x, 2 * x + 1, color);
  }
}

// Filled triangle — sweep two edges per scanline. Sorted Y0 ≤ Y1 ≤ Y2.
void Arduino_GFX::fillTriangle(int16_t x0, int16_t y0, int16_t x1, int16_t y1,
                               int16_t x2, int16_t y2, uint16_t color) {
  if (y0 > y1) { std::swap(y0, y1); std::swap(x0, x1); }
  if (y1 > y2) { std::swap(y2, y1); std::swap(x2, x1); }
  if (y0 > y1) { std::swap(y0, y1); std::swap(x0, x1); }

  if (y0 == y2) {
    int16_t a = x0, b = x0;
    if (x1 < a) a = x1; else if (x1 > b) b = x1;
    if (x2 < a) a = x2; else if (x2 > b) b = x2;
    drawFastHLine(a, y0, b - a + 1, color);
    return;
  }

  int16_t dx01 = x1 - x0, dy01 = y1 - y0;
  int16_t dx02 = x2 - x0, dy02 = y2 - y0;
  int16_t dx12 = x2 - x1, dy12 = y2 - y1;
  int32_t sa = 0, sb = 0;

  int16_t last = (y1 == y2) ? y1 : y1 - 1;
  for (int16_t y = y0; y <= last; y++) {
    int16_t a = x0 + sa / dy01;
    int16_t b = x0 + sb / dy02;
    sa += dx01; sb += dx02;
    if (a > b) std::swap(a, b);
    drawFastHLine(a, y, b - a + 1, color);
  }
  sa = (int32_t)dx12 * (last + 1 - y1);
  sb = (int32_t)dx02 * (last + 1 - y0);
  for (int16_t y = last + 1; y <= y2; y++) {
    int16_t a = x1 + sa / dy12;
    int16_t b = x0 + sb / dy02;
    sa += dx12; sb += dx02;
    if (a > b) std::swap(a, b);
    drawFastHLine(a, y, b - a + 1, color);
  }
}

// Rounded-rect helper: 1/4-circle plus straight segments.
static void _quarterCircleHelper(Arduino_GFX* g, int16_t cx, int16_t cy, int16_t r,
                                  uint8_t corner, uint16_t color) {
  int16_t x = 0, y = r;
  int16_t f = 1 - r, ddF_x = 1, ddF_y = -2 * r;
  while (x < y) {
    if (f >= 0) { y--; ddF_y += 2; f += ddF_y; }
    x++; ddF_x += 2; f += ddF_x;
    if (corner & 0x4) { g->drawPixel(cx + x, cy + y, color); g->drawPixel(cx + y, cy + x, color); }
    if (corner & 0x2) { g->drawPixel(cx + x, cy - y, color); g->drawPixel(cx + y, cy - x, color); }
    if (corner & 0x8) { g->drawPixel(cx - y, cy + x, color); g->drawPixel(cx - x, cy + y, color); }
    if (corner & 0x1) { g->drawPixel(cx - y, cy - x, color); g->drawPixel(cx - x, cy - y, color); }
  }
}
static void _fillQuarterCircleHelper(Arduino_GFX* g, int16_t cx, int16_t cy, int16_t r,
                                      uint8_t corner, int16_t delta, uint16_t color) {
  int16_t x = 0, y = r;
  int16_t f = 1 - r, ddF_x = 1, ddF_y = -2 * r;
  int16_t px = x, py = y;
  delta++;
  while (x < y) {
    if (f >= 0) { y--; ddF_y += 2; f += ddF_y; }
    x++; ddF_x += 2; f += ddF_x;
    if (x < (y + 1)) {
      if (corner & 1) g->drawFastVLine(cx + x, cy - y, 2 * y + delta, color);
      if (corner & 2) g->drawFastVLine(cx - x, cy - y, 2 * y + delta, color);
    }
    if (y != py) {
      if (corner & 1) g->drawFastVLine(cx + py, cy - px, 2 * px + delta, color);
      if (corner & 2) g->drawFastVLine(cx - py, cy - px, 2 * px + delta, color);
      py = y;
    }
    px = x;
  }
}

void Arduino_GFX::drawRoundRect(int16_t x, int16_t y, int16_t w, int16_t h,
                                int16_t r, uint16_t color) {
  int16_t maxR = ((w < h) ? w : h) / 2;
  if (r > maxR) r = maxR;
  drawFastHLine(x + r,         y,         w - 2 * r, color);
  drawFastHLine(x + r,         y + h - 1, w - 2 * r, color);
  drawFastVLine(x,             y + r,     h - 2 * r, color);
  drawFastVLine(x + w - 1,     y + r,     h - 2 * r, color);
  _quarterCircleHelper(this, x + r,         y + r,         r, 1, color);
  _quarterCircleHelper(this, x + w - r - 1, y + r,         r, 2, color);
  _quarterCircleHelper(this, x + w - r - 1, y + h - r - 1, r, 4, color);
  _quarterCircleHelper(this, x + r,         y + h - r - 1, r, 8, color);
}

void Arduino_GFX::fillRoundRect(int16_t x, int16_t y, int16_t w, int16_t h,
                                int16_t r, uint16_t color) {
  int16_t maxR = ((w < h) ? w : h) / 2;
  if (r > maxR) r = maxR;
  fillRect(x + r, y, w - 2 * r, h, color);
  _fillQuarterCircleHelper(this, x + w - r - 1, y + r, r, 1, h - 2 * r - 1, color);
  _fillQuarterCircleHelper(this, x + r,         y + r, r, 2, h - 2 * r - 1, color);
}

void Arduino_GFX::draw16bitRGBBitmap(int16_t x, int16_t y, const uint16_t* bitmap,
                                     int16_t w, int16_t h) {
  for (int16_t j = 0; j < h; j++)
    for (int16_t i = 0; i < w; i++)
      drawPixel(x + i, y + j, bitmap[j * w + i]);
}

// ──────────────── Text rendering ────────────────

void Arduino_GFX::drawCharBuiltin(int16_t x, int16_t y, char c,
                                  uint16_t fg, uint16_t bg, uint8_t size) {
  if ((uint8_t)c >= 128) c = '?';
  const uint8_t* glyph = sim_font_5x7[(uint8_t)c];
  for (int8_t col = 0; col < 6; col++) {
    uint8_t bits = (col < 5) ? glyph[col] : 0;
    for (int8_t row = 0; row < 8; row++) {
      bool on = bits & (1 << row);
      uint16_t color = on ? fg : bg;
      if (!on && !_tbgEnabled) continue;
      if (size == 1) {
        drawPixel(x + col, y + row, color);
      } else {
        fillRect(x + col * size, y + row * size, size, size, color);
      }
    }
  }
}

// Decode one UTF-8 codepoint from p..end; advance p past the bytes consumed.
uint32_t Arduino_GFX::advanceUtf8(const char*& p, const char* end) {
  if (p >= end) return 0;
  uint8_t b0 = (uint8_t)*p++;
  if (b0 < 0x80) return b0;
  uint32_t cp = 0; int extra = 0;
  if      ((b0 & 0xE0) == 0xC0) { cp = b0 & 0x1F; extra = 1; }
  else if ((b0 & 0xF0) == 0xE0) { cp = b0 & 0x0F; extra = 2; }
  else if ((b0 & 0xF8) == 0xF0) { cp = b0 & 0x07; extra = 3; }
  else return '?';
  for (int i = 0; i < extra && p < end; i++) {
    uint8_t bn = (uint8_t)*p++;
    if ((bn & 0xC0) != 0x80) return '?';
    cp = (cp << 6) | (bn & 0x3F);
  }
  return cp;
}

// Forward-decl for the U8g2 path (sim_u8g2.cpp).
extern int  simU8g2DrawGlyph(Arduino_GFX* g, const uint8_t* font,
                             int16_t x, int16_t y, uint32_t cp,
                             uint16_t fg, uint16_t bg, bool bgEnabled);
extern int  simU8g2GlyphWidth(const uint8_t* font, uint32_t cp);
extern void simU8g2FontMetrics(const uint8_t* font,
                               int* ascent, int* descent, int* lineHeight);

size_t Arduino_GFX::print(char c) {
  return printOneCodepoint((uint8_t)c);
}

size_t Arduino_GFX::print(const char* s) {
  if (!s) return 0;
  const char* p   = s;
  const char* end = s + std::strlen(s);
  size_t n = 0;
  while (p < end) {
    uint32_t cp = _utf8 ? advanceUtf8(p, end) : (uint8_t)*p++;
    n += printOneCodepoint(cp);
  }
  return n;
}

size_t Arduino_GFX::println(const char* s) {
  size_t n = print(s);
  // Builtin font advances cursor; \n moves to next line.
  _cy += 8 * _tsize;
  _cx = 0;
  return n + 1;
}

size_t Arduino_GFX::printf(const char* fmt, ...) {
  char buf[256];
  va_list ap; va_start(ap, fmt);
  int n = std::vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  if (n < 0) return 0;
  return print(buf);
}

size_t Arduino_GFX::printOneCodepoint(uint32_t cp) {
  if (cp == '\n') { _cy += 8 * _tsize; _cx = 0; return 1; }
  if (cp == '\r') { _cx = 0; return 1; }
  if (_u8g2Font) {
    int adv = simU8g2DrawGlyph(this, _u8g2Font, _cx, _cy, cp, _tfg, _tbg, _tbgEnabled);
    _cx += adv;
  } else {
    char ch = (cp < 128) ? (char)cp : '?';
    drawCharBuiltin(_cx, _cy, ch, _tfg, _tbg, _tsize);
    _cx += 6 * _tsize;
  }
  return 1;
}

// ──────────────── Arduino_Canvas (RGB565 framebuffer) ────────────────

Arduino_Canvas::Arduino_Canvas(int16_t w, int16_t h, void* /*output*/) : Arduino_GFX(w, h) {}
Arduino_Canvas::~Arduino_Canvas() { std::free(_fb); }

bool Arduino_Canvas::begin() {
  _fb = (uint16_t*)std::calloc((size_t)_w * _h, sizeof(uint16_t));
  return _fb != nullptr;
}

void Arduino_Canvas::fillScreen(uint16_t color) {
  for (int n = _w * _h, i = 0; i < n; i++) _fb[i] = color;
}

void Arduino_Canvas::drawPixel(int16_t x, int16_t y, uint16_t color) {
  if (x < 0 || y < 0 || x >= _w || y >= _h) return;
  _fb[y * _w + x] = color;
}

void Arduino_Canvas::fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color) {
  if (x < 0) { w += x; x = 0; }
  if (y < 0) { h += y; y = 0; }
  if (x + w > _w) w = _w - x;
  if (y + h > _h) h = _h - y;
  if (w <= 0 || h <= 0) return;
  for (int16_t j = 0; j < h; j++) {
    uint16_t* row = _fb + (y + j) * _w + x;
    for (int16_t i = 0; i < w; i++) row[i] = color;
  }
}

void Arduino_Canvas::drawRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color) {
  drawFastHLine(x,         y,         w, color);
  drawFastHLine(x,         y + h - 1, w, color);
  drawFastVLine(x,         y,         h, color);
  drawFastVLine(x + w - 1, y,         h, color);
}

void Arduino_Canvas::drawFastHLine(int16_t x, int16_t y, int16_t w, uint16_t color) {
  if (y < 0 || y >= _h) return;
  if (x < 0) { w += x; x = 0; }
  if (x + w > _w) w = _w - x;
  if (w <= 0) return;
  uint16_t* row = _fb + y * _w + x;
  for (int16_t i = 0; i < w; i++) row[i] = color;
}

void Arduino_Canvas::drawFastVLine(int16_t x, int16_t y, int16_t h, uint16_t color) {
  if (x < 0 || x >= _w) return;
  if (y < 0) { h += y; y = 0; }
  if (y + h > _h) h = _h - y;
  if (h <= 0) return;
  for (int16_t j = 0; j < h; j++) _fb[(y + j) * _w + x] = color;
}

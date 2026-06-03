#pragma once
// Minimal Arduino_GFX surface used by claude-desktop-buddy-esp32 firmware.
// Only the methods main.cpp / buddy*.cpp / character.cpp actually call.
//
// This header defines the public API; the implementation lives in
// sim/src/sim_gfx.cpp. The same Arduino_Canvas* the firmware draws into is
// what hwDisplayPush() reads back via getFramebuffer().

#include <Arduino.h>
#include <cstdint>

// GFXfont — firmware passes NULL to setFont(GFXfont*) to reset to the
// built-in bitmap font. We only use the pointer identity, never the contents.
struct GFXfont;

class Arduino_GFX {
public:
  Arduino_GFX(int16_t w, int16_t h);
  virtual ~Arduino_GFX();

  int16_t width()  const { return _w; }
  int16_t height() const { return _h; }

  virtual void fillScreen(uint16_t color);
  virtual void drawPixel(int16_t x, int16_t y, uint16_t color);
  virtual void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color);
  virtual void drawRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color);
  virtual void fillRoundRect(int16_t x, int16_t y, int16_t w, int16_t h, int16_t r, uint16_t color);
  virtual void drawRoundRect(int16_t x, int16_t y, int16_t w, int16_t h, int16_t r, uint16_t color);
  virtual void fillCircle(int16_t cx, int16_t cy, int16_t r, uint16_t color);
  virtual void drawCircle(int16_t cx, int16_t cy, int16_t r, uint16_t color);
  virtual void fillTriangle(int16_t x0, int16_t y0, int16_t x1, int16_t y1,
                            int16_t x2, int16_t y2, uint16_t color);
  virtual void drawLine(int16_t x0, int16_t y0, int16_t x1, int16_t y1, uint16_t color);
  virtual void drawFastHLine(int16_t x, int16_t y, int16_t w, uint16_t color);
  virtual void drawFastVLine(int16_t x, int16_t y, int16_t h, uint16_t color);

  // Text
  void setCursor(int16_t x, int16_t y) { _cx = x; _cy = y; }
  void setTextColor(uint16_t fg)                 { _tfg = fg; _tbg = fg; _tbgEnabled = false; }
  void setTextColor(uint16_t fg, uint16_t bg)    { _tfg = fg; _tbg = bg; _tbgEnabled = true;  }
  void setTextSize(uint8_t s) { _tsize = s ? s : 1; }
  void setFont(const GFXfont* f) { _gfxFont = f; _u8g2Font = nullptr; }
  void setFont(const uint8_t* u8g2)   { _u8g2Font = u8g2; _gfxFont = nullptr; }
  void setUTF8Print(bool on) { _utf8 = on; }

  size_t print(char c);
  size_t print(const char* s);
  size_t println(const char* s);
  size_t printf(const char* fmt, ...);

  // GIF / one-shot bitmap blit (called from character.cpp draw callback).
  virtual void draw16bitRGBBitmap(int16_t x, int16_t y, const uint16_t* bitmap,
                                  int16_t w, int16_t h);

protected:
  int16_t  _w, _h;
  int16_t  _cx = 0, _cy = 0;
  uint16_t _tfg = 0xFFFF, _tbg = 0x0000;
  bool     _tbgEnabled = true;
  uint8_t  _tsize = 1;
  const GFXfont* _gfxFont = nullptr;
  const uint8_t* _u8g2Font = nullptr;
  bool     _utf8 = false;

  void drawCharBuiltin(int16_t x, int16_t y, char c, uint16_t fg, uint16_t bg, uint8_t size);
  size_t printOneCodepoint(uint32_t cp);
  uint32_t advanceUtf8(const char*& p, const char* end);
};

// Arduino_Canvas — RGB565 framebuffer that hwDisplayPush() reads back.
// On real hw it's PSRAM-backed; on the sim it's plain heap.
class Arduino_Canvas : public Arduino_GFX {
public:
  Arduino_Canvas(int16_t w, int16_t h, void* /*output*/ = nullptr);
  ~Arduino_Canvas() override;
  bool begin();

  void fillScreen(uint16_t color) override;
  void drawPixel(int16_t x, int16_t y, uint16_t color) override;
  void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color) override;
  void drawRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color) override;
  void drawFastHLine(int16_t x, int16_t y, int16_t w, uint16_t color) override;
  void drawFastVLine(int16_t x, int16_t y, int16_t h, uint16_t color) override;

  uint16_t* getFramebuffer() { return _fb; }

private:
  uint16_t* _fb = nullptr;
};

// The CO5300 / SH8601 / DataBus / QSPI types are referenced only in
// src/hw/display.cpp, which the sim build replaces with hw_display_sim.cpp.
// These forward-decls let other includes parse without error if anything
// reaches for them.
class Arduino_DataBus;
class Arduino_CO5300;
class Arduino_SH8601;
class Arduino_ESP32QSPI;
#define GFX_NOT_DEFINED -1

// Arduino_GFX bundles a handful of U8g2 font tables. Firmware references
// `u8g2_font_chill7_h_cjk` directly; provide a forward declaration so the
// firmware compiles. The actual storage lives in sim/src/sim_u8g2_stub.cpp
// (M1: single-byte placeholder; M2: real glyph table).
extern "C" const uint8_t u8g2_font_chill7_h_cjk[];

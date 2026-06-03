// SDL2 viewport + letterbox + 90° CCW rotation.
//
// The firmware writes RGB565 into a 184×224 canvas. On the real CO5300
// panel, hwDisplayPush() bilinear-scales that to 368×448 (exact 2×),
// centres it at (56, 16) inside the 480×480 frame buffer, then the
// panel's MADCTL=0xA0 (MV+MY) rotates the whole frame 90° CCW for
// display. We mirror that pipeline pixel-for-pixel so the sim window
// shows what the real device will show.
//
// The bilinear-scale loop here is ported verbatim from
// src/hw/display.cpp:151-184 — see comments there for the RGB565 trick.

#include "sim_panel.h"
#include <SDL.h>
#include <cstdio>
#include <cstring>

// Mirror the board header rather than including it (board headers are
// firmware-side; this file only needs the constants).
static constexpr int LCD_W_PHYS = 480;
static constexpr int LCD_H_PHYS = 480;
static constexpr int HW_W       = 184;
static constexpr int HW_H       = 224;
static constexpr int DEST_W     = 368;
static constexpr int DEST_H     = 448;
static constexpr int OFF_X      = (LCD_W_PHYS - DEST_W) / 2;   // 56
static constexpr int OFF_Y      = (LCD_H_PHYS - DEST_H) / 2;   // 16

static constexpr uint32_t SCALE_X = ((uint32_t)HW_W << 16) / DEST_W;
static constexpr uint32_t SCALE_Y = ((uint32_t)HW_H << 16) / DEST_H;

static SDL_Window*   s_window   = nullptr;
static SDL_Renderer* s_renderer = nullptr;
static SDL_Texture*  s_tex      = nullptr;     // 480×480 RGB565

static SimMouse s_mouse{};
static SimKeys  s_keys{};
static bool     s_usb_edge = false;

bool simPanelInit(const char* title) {
  if (SDL_Init(SDL_INIT_VIDEO) != 0) {
    std::fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
    return false;
  }
  s_window = SDL_CreateWindow(title,
      SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
      LCD_W_PHYS, LCD_H_PHYS, SDL_WINDOW_SHOWN);
  if (!s_window) { std::fprintf(stderr, "SDL_CreateWindow: %s\n", SDL_GetError()); return false; }
  s_renderer = SDL_CreateRenderer(s_window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
  if (!s_renderer) { std::fprintf(stderr, "SDL_CreateRenderer: %s\n", SDL_GetError()); return false; }
  s_tex = SDL_CreateTexture(s_renderer, SDL_PIXELFORMAT_RGB565,
                            SDL_TEXTUREACCESS_STREAMING, LCD_W_PHYS, LCD_H_PHYS);
  if (!s_tex) { std::fprintf(stderr, "SDL_CreateTexture: %s\n", SDL_GetError()); return false; }
  return true;
}

void simPanelShutdown() {
  if (s_tex)      SDL_DestroyTexture(s_tex);
  if (s_renderer) SDL_DestroyRenderer(s_renderer);
  if (s_window)   SDL_DestroyWindow(s_window);
  SDL_Quit();
}

// Reverse the letterbox + 90° CW rotation so a click at SDL window
// coord (x_w, y_w) maps to a canvas (cx, cy) in 0..HW_W-1 / 0..HW_H-1.
//
// Forward path (canvas → window):
//   letterbox: (cx, cy) → (OFF_X + cx*DEST_W/HW_W, OFF_Y + cy*DEST_H/HW_H) = (rx, ry)
//   rotate 90° CW: (rx, ry) → (LCD_H_PHYS-1 - ry, rx) = (xw, yw)
// Reverse:
//   undo rotation: rx = yw;  ry = LCD_H_PHYS-1 - xw
//   undo letterbox: cx = (rx - OFF_X) * HW_W / DEST_W
//                   cy = (ry - OFF_Y) * HW_H / DEST_H
static void mouseToCanvas(int xw, int yw, SimMouse& m) {
  int rx = yw;
  int ry = LCD_H_PHYS - 1 - xw;
  int cx = (rx - OFF_X) * HW_W / DEST_W;
  int cy = (ry - OFF_Y) * HW_H / DEST_H;
  m.cx = (int16_t)cx;
  m.cy = (int16_t)cy;
  m.valid = (cx >= 0 && cx < HW_W && cy >= 0 && cy < HW_H);
}

bool simPanelPumpEvents() {
  s_usb_edge = false;
  SDL_Event e;
  while (SDL_PollEvent(&e)) {
    switch (e.type) {
      case SDL_QUIT: return false;
      case SDL_KEYDOWN:
      case SDL_KEYUP: {
        bool down = (e.type == SDL_KEYDOWN);
        switch (e.key.keysym.sym) {
          case SDLK_SPACE: case SDLK_RETURN: s_keys.key1 = down; break;
          case SDLK_b: case SDLK_RIGHT:      s_keys.key2 = down; break;
          case SDLK_m:                       s_keys.keyBoot = down; break;
          case SDLK_s:                       s_keys.shake = down; break;
          case SDLK_f:
            if (down && !e.key.repeat) s_keys.faceDown = !s_keys.faceDown;
            break;
          case SDLK_u:
            if (down && !e.key.repeat) { s_keys.usbToggle = !s_keys.usbToggle; s_usb_edge = true; }
            break;
          case SDLK_ESCAPE:
            if (down) return false;
            break;
        }
        break;
      }
      case SDL_MOUSEBUTTONDOWN:
        if (e.button.button == SDL_BUTTON_LEFT) {
          s_mouse.down = true;
          mouseToCanvas(e.button.x, e.button.y, s_mouse);
        }
        break;
      case SDL_MOUSEBUTTONUP:
        if (e.button.button == SDL_BUTTON_LEFT) {
          s_mouse.down = false;
          mouseToCanvas(e.button.x, e.button.y, s_mouse);
        }
        break;
      case SDL_MOUSEMOTION:
        if (s_mouse.down) mouseToCanvas(e.motion.x, e.motion.y, s_mouse);
        break;
    }
  }
  return true;
}

SimMouse simPanelMouse() { return s_mouse; }
const SimKeys& simPanelKeys() { return s_keys; }

void simPanelPush(const uint16_t* src, uint8_t brightness, bool border_alert) {
  if (!s_renderer || !s_tex) return;

  // Lock the texture and write the unrotated, letterboxed 480×480 frame.
  // We rotate visually via SDL_RenderCopyEx below, so the framebuffer
  // we hand SDL is the same shape as the firmware's s_frameBuf.
  uint16_t* pixels = nullptr;
  int pitch = 0;
  if (SDL_LockTexture(s_tex, nullptr, (void**)&pixels, &pitch) != 0) return;
  // Letterbox: black surround, scaled canvas centred at (OFF_X, OFF_Y).
  std::memset(pixels, 0, pitch * LCD_H_PHYS);

  for (int dy = 0; dy < DEST_H; dy++) {
    uint32_t sy_fp = (uint32_t)dy * SCALE_Y;
    int y0 = sy_fp >> 16;
    int y1 = (y0 + 1 < HW_H) ? y0 + 1 : y0;
    uint32_t fy = (sy_fp >> 11) & 0x1F;
    uint32_t inv_fy = 32 - fy;

    const uint16_t* row0 = src + y0 * HW_W;
    const uint16_t* row1 = src + y1 * HW_W;
    uint16_t* dstRow = pixels + (dy + OFF_Y) * (pitch / 2) + OFF_X;

    for (int dx = 0; dx < DEST_W; dx++) {
      uint32_t sx_fp = (uint32_t)dx * SCALE_X;
      int x0 = sx_fp >> 16;
      int x1 = (x0 + 1 < HW_W) ? x0 + 1 : x0;
      uint32_t fx = (sx_fp >> 11) & 0x1F;
      uint32_t inv_fx = 32 - fx;

      uint16_t p00 = row0[x0];
      uint16_t p01 = row0[x1];
      uint16_t p10 = row1[x0];
      uint16_t p11 = row1[x1];

      uint32_t t_rb = (p00 & 0xF81F) * inv_fx + (p01 & 0xF81F) * fx;
      uint32_t t_g  = (p00 & 0x07E0) * inv_fx + (p01 & 0x07E0) * fx;
      uint32_t b_rb = (p10 & 0xF81F) * inv_fx + (p11 & 0xF81F) * fx;
      uint32_t b_g  = (p10 & 0x07E0) * inv_fx + (p11 & 0x07E0) * fx;

      uint32_t rb = (t_rb * inv_fy + b_rb * fy) >> 10;
      uint32_t g  = (t_g  * inv_fy + b_g  * fy) >> 10;

      dstRow[dx] = (uint16_t)((rb & 0xF81F) | (g & 0x07E0));
    }
  }

  // Border alert: red rounded pill at the top of the (pre-rotation)
  // physical frame. Same coords as src/hw/display.cpp:237-243.
  if (border_alert) {
    const int BAR_W = 200;
    const int BAR_H = 8;
    const int BAR_Y = 18;
    const int BAR_X = (LCD_W_PHYS - BAR_W) / 2;
    const uint16_t RED = 0xF800;
    for (int y = BAR_Y; y < BAR_Y + BAR_H; y++) {
      uint16_t* r = pixels + y * (pitch / 2);
      for (int x = BAR_X; x < BAR_X + BAR_W; x++) r[x] = RED;
    }
  }

  SDL_UnlockTexture(s_tex);

  SDL_SetRenderDrawColor(s_renderer, 0, 0, 0, 255);
  SDL_RenderClear(s_renderer);

  // Rotate 90° clockwise visually. SDL_RenderCopyEx rotates clockwise
  // by `angle` degrees, so pass +90.
  SDL_SetTextureAlphaMod(s_tex, brightness);
  SDL_RenderCopyEx(s_renderer, s_tex, nullptr, nullptr, 90.0, nullptr, SDL_FLIP_NONE);
  SDL_RenderPresent(s_renderer);
}

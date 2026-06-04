#include "../buddy.h"
#include "../buddy_common.h"
#include <string.h>

namespace dog {

// Sprite layout (12 chars wide, 5 lines, rendered at 2× in sim):
//   line 0: topknot { } or overlay particles
//   line 1: ears + eyes + nose   /(> o <)\
//   line 2: muzzle expression    ( -w-  )
//   line 3: legs                 /|    |\
//   line 4: paws + tail          _n_u-u_n_/)

// ─── SLEEP ─── slow breath, droopy eyes, floating Z's
static void doSleep(uint32_t t) {
  static const char* const SIT[5]   = { "    { }     ", " /(- o -)\\  ", " (  ~~~  )  ", "  /|    |\\  ", " _n_u-u_n_  " };
  static const char* const SNORE[5] = { "    { }     ", " /(- o -)\\  ", " ( wwwww )  ", "  /|    |\\  ", " _n_u-u_n_  " };
  static const char* const DROOP[5] = { "    { }     ", " /(- o -)\\  ", " (  ~~~  )  ", "  /|    |\\  ", " _n_u-u_n_  " };

  const char* const* P[3] = { SIT, SNORE, DROOP };
  static const uint8_t SEQ[] = {
    0,0,0,0,0, 1,0,0,0, 2,2,0,0, 0,1,0,0, 2,0,0,0,1
  };
  uint8_t beat = (t / 6) % sizeof(SEQ);
  buddyPrintSprite(P[SEQ[beat]], 5, 0, 0xD5B1);

  int p1 = t % 12;
  int p2 = (t + 5) % 12;
  int p3 = (t + 9) % 12;
  buddySetColor(BUDDY_DIM);
  buddySetCursor(BUDDY_X_CENTER + 18 + p1, BUDDY_Y_OVERLAY + 16 - p1 * 2);
  buddyPrint("z");
  buddySetColor(BUDDY_WHITE);
  buddySetCursor(BUDDY_X_CENTER + 22 + p2, BUDDY_Y_OVERLAY + 12 - p2);
  buddyPrint("Z");
  buddySetColor(BUDDY_DIM);
  buddySetCursor(BUDDY_X_CENTER + 14 + p3 / 2, BUDDY_Y_OVERLAY + 8 - p3 / 2);
  buddyPrint("z");
}

// ─── IDLE ─── alert sit, looks around, tail wags every 3 ticks
static void doIdle(uint32_t t) {
  static const char* const REST[5]   = { "    { }     ", " /(> o <)\\  ", " (  -w-  )  ", "  /|    |\\  ", " _n_u-u_n_  " };
  static const char* const REST_T[5] = { "    { }     ", " /(> o <)\\  ", " (  -w-  )  ", "  /|    |\\  ", " _n_u-u_n_/)" };
  static const char* const BLINK[5]  = { "    { }     ", " /(- o -)\\  ", " (  -w-  )  ", "  /|    |\\  ", " _n_u-u_n_/)" };
  static const char* const LOOK_L[5] = { "    { }     ", " /(. o <)\\  ", " (  -w-  )  ", "  /|    |\\  ", " _n_u-u_n_/)" };
  static const char* const LOOK_R[5] = { "    { }     ", " /(> o .)\\  ", " (  -w-  )  ", "  /|    |\\  ", " _n_u-u_n_/)" };

  bool tail = (t / 3) & 1;
  const char* const* P[5] = { tail ? REST_T : REST, BLINK, LOOK_L, LOOK_R, REST_T };
  static const uint8_t SEQ[] = {
    0,0,0,1,0, 0,2,0,0, 0,1,0,3,0, 0,1,0,0, 2,0,0
  };
  uint8_t beat = (t / 5) % sizeof(SEQ);
  buddyPrintSprite(P[SEQ[beat]], 5, 0, 0xD5B1);
}

// ─── BUSY ─── panting, focused
static void doBusy(uint32_t t) {
  static const char* const PANT_A[5] = { "    { }     ", " /(> o >)\\  ", " (  www  )  ", "  /|    |\\  ", " _n_u-u_n_  " };
  static const char* const PANT_B[5] = { "    { }     ", " /(> o >)\\  ", " ( wwwww )  ", "  /|    |\\  ", " _n_u-u_n_  " };
  static const char* const FOCUS[5]  = { "    { }     ", " /(> o >)\\  ", " (  -w-  )  ", "  /|    |\\  ", " _n_u-u_n_  " };

  const char* const* P[3] = { PANT_A, PANT_B, FOCUS };
  static const uint8_t SEQ[] = {
    0,1,0,1,0,1, 2,2, 0,1,0,1, 2,2, 0,1,0,1,0,1
  };
  uint8_t beat = (t / 4) % sizeof(SEQ);
  buddyPrintSprite(P[SEQ[beat]], 5, 0, 0xD5B1);

  static const char* const DOTS[] = { "   ", " . ", " . ", ".. ", ".  " };
  buddySetColor(BUDDY_WHITE);
  buddySetCursor(BUDDY_X_CENTER + 22, BUDDY_Y_OVERLAY + 16);
  buddyPrint(DOTS[t % 5]);
}

// ─── ATTENTION ─── big eyes, scanning, bark + flashing !
static void doAttention(uint32_t t) {
  static const char* const ALERT[5]  = { "    { }     ", " /(O o O)\\  ", " (  !!!  )  ", "  /|    |\\  ", " _n_u-u_n_  " };
  static const char* const SCAN_L[5] = { "    { }     ", " /(O o O)\\  ", " (  -w-  )  ", "  /|    |\\  ", " _n_u-u_n_  " };
  static const char* const SCAN_R[5] = { "    { }     ", " /(O o O)\\  ", " (  -w-  )  ", "  /|    |\\  ", " _n_u-u_n_  " };
  static const char* const BARK[5]   = { "    { }     ", " /(O o O)\\  ", " (  www  )  ", " /|      |\\ ", " _n_u-u_n_  " };

  const char* const* P[4] = { ALERT, SCAN_L, SCAN_R, BARK };
  static const uint8_t SEQ[] = {
    0,1,0,2,0,1, 3,3, 0,1,0,2, 3,3, 0,1,0
  };
  uint8_t beat = (t / 5) % sizeof(SEQ);
  uint8_t pose = SEQ[beat];
  int xOff = (pose == 1) ? -2 : (pose == 2) ? 2 : 0;
  buddyPrintSprite(P[pose], 5, 0, 0xD5B1, xOff);

  if ((t / 2) & 1) {
    buddySetColor(BUDDY_YEL);
    buddySetCursor(BUDDY_X_CENTER - 6, BUDDY_Y_OVERLAY);
    buddyPrint("!");
  }
  if ((t / 3) & 1) {
    buddySetColor(BUDDY_YEL);
    buddySetCursor(BUDDY_X_CENTER + 6, BUDDY_Y_OVERLAY + 4);
    buddyPrint("!");
  }
}

// ─── CELEBRATE ─── jump, happy eyes, confetti
static void doCelebrate(uint32_t t) {
  static const char* const CROUCH[5] = { "    { }     ", " /(^ o ^)\\  ", " (  www  )  ", "  /|    |\\  ", " _n_u-u_n_  " };
  static const char* const JUMP[5]   = { "\\(        )/", " /(^ o ^)\\  ", " (  www  )  ", "   |    |   ", " _n_   _n_  " };
  static const char* const PEAK[5]   = { "\\(        )/", " /(^ o ^)\\  ", " ( wwwww )  ", "   |    |   ", "  _n_ _n_   " };

  const char* const* P[3] = { CROUCH, JUMP, PEAK };
  static const uint8_t SEQ[]  = { 0,1,2,1,0, 1,2,1,0, 0,1,2,2,1,0, 0 };
  static const int8_t  Y_UP[] = { 0,-3,-6,-3,0, -3,-6,-3,0, 0,-3,-6,-6,-3,0, 0 };
  uint8_t beat = (t / 3) % sizeof(SEQ);
  buddyPrintSprite(P[SEQ[beat]], 5, Y_UP[beat], 0xD5B1);

  static const uint16_t cols[] = { BUDDY_YEL, BUDDY_HEART, BUDDY_CYAN, BUDDY_WHITE, BUDDY_GREEN };
  for (int i = 0; i < 6; i++) {
    int phase = (t * 2 + i * 11) % 22;
    int x = BUDDY_X_CENTER - 36 + i * 14;
    int y = BUDDY_Y_OVERLAY - 6 + phase;
    if (y > BUDDY_Y_BASE + 20 || y < 0) continue;
    buddySetColor(cols[i % 5]);
    buddySetCursor(x, y);
    buddyPrint((i + (int)(t / 2)) & 1 ? "*" : ".");
  }
}

// ─── DIZZY ─── tilting, mixed-up eyes, orbiting stars
static void doDizzy(uint32_t t) {
  static const char* const TILT_L[5] = { "    { }     ", " /(@ o x)\\  ", " (  ~~~  )  ", "  /|    |\\  ", " _n_u-u_n_  " };
  static const char* const TILT_R[5] = { "    { }     ", " /(x o @)\\  ", " (  ~~~  )  ", "  /|    |\\  ", " _n_u-u_n_  " };
  static const char* const WOOZY[5]  = { "    { }     ", " /(@ o @)\\  ", " ( ~~~~~ )  ", "  /|    |\\  ", " _n_u-u_n_  " };

  const char* const* P[3] = { TILT_L, TILT_R, WOOZY };
  static const uint8_t SEQ[]  = { 0,1,0,1, 2,2, 0,1,0,1, 2,2, 0,1 };
  static const int8_t  X_SH[] = { -3,3,-3,3, 0,0, -3,3,-3,3, 0,0, -3,3 };
  uint8_t beat = (t / 4) % sizeof(SEQ);
  buddyPrintSprite(P[SEQ[beat]], 5, 0, 0xD5B1, X_SH[beat]);

  static const int8_t OX[] = { 0, 5, 7, 5, 0, -5, -7, -5 };
  static const int8_t OY[] = { -5,-3, 0, 3, 5,  3,  0, -3 };
  uint8_t p1 = t % 8, p2 = (t + 4) % 8;
  buddySetColor(BUDDY_CYAN);
  buddySetCursor(BUDDY_X_CENTER + OX[p1] - 2, BUDDY_Y_OVERLAY + 6 + OY[p1]);
  buddyPrint("*");
  buddySetColor(BUDDY_YEL);
  buddySetCursor(BUDDY_X_CENTER + OX[p2] - 2, BUDDY_Y_OVERLAY + 6 + OY[p2]);
  buddyPrint("*");
}

// ─── HEART ─── uwu eyes, fast tail wag, rising hearts
static void doHeart(uint32_t t) {
  static const char* const DREAMY[5]   = { " <3      <3 ", " /(^ o ^)\\  ", " (  uwu  )  ", "  /|    |\\  ", " _n_u-u_n_  " };
  static const char* const DREAMY_T[5] = { " <3      <3 ", " /(^ o ^)\\  ", " (  uwu  )  ", "  /|    |\\  ", " _n_u-u_n_/)" };
  static const char* const BLUSH[5]    = { " <3      <3 ", " /(^ o ^)\\  ", " ( uwuwu )  ", "  /|    |\\  ", " _n_u-u_n_/)" };

  bool tail = (t / 2) & 1;
  const char* const* P[3] = { tail ? DREAMY_T : DREAMY, BLUSH, DREAMY_T };
  static const uint8_t SEQ[]   = { 0,0,1,0, 2,2,0, 1,0,0, 0,1,0, 2,0 };
  static const int8_t  Y_BOB[] = { -1,-2,-1,-2, -1,-2,-1, -2,-1,-1, -1,-2,-1, -1,-1 };
  uint8_t beat = (t / 5) % sizeof(SEQ);
  buddyPrintSprite(P[SEQ[beat]], 5, Y_BOB[beat], 0xD5B1);

  buddySetColor(BUDDY_HEART);
  for (int i = 0; i < 5; i++) {
    int phase = (t + i * 4) % 16;
    int y = BUDDY_Y_OVERLAY + 16 - phase;
    if (y < -2 || y > BUDDY_Y_BASE) continue;
    int x = BUDDY_X_CENTER - 20 + i * 8 + ((phase / 3) & 1) * 2 - 1;
    buddySetCursor(x, y);
    buddyPrint("v");
  }
}

} // namespace dog

extern const Species DOG_SPECIES = {
  "dog",
  0xD5B1,
  { dog::doSleep, dog::doIdle, dog::doBusy, dog::doAttention,
    dog::doCelebrate, dog::doDizzy, dog::doHeart }
};

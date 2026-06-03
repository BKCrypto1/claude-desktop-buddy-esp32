// Sim replacement for src/hw/hw.cpp.
// The real one calls Wire.begin / expander reset / display reset etc.
// In the sim none of that exists — just init the subsystems in order.

#include "hw/hw.h"
#include <Arduino.h>

void hwInit() {
  Serial.println("\n=== claude-buddy SIM boot ===");
  hwExpanderInit();
  hwDisplayInit();
  hwPowerInit();
  hwInputInit();
  hwImuInit();
  hwRtcInit();
  hwAudioInit();
  Serial.println("hwInit OK");
}

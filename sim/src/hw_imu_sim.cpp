#include "hw/imu.h"
#include <Arduino.h>
#include "sim_panel.h"

bool hwImuInit() { return true; }

void hwImuAccel(float* ax, float* ay, float* az) {
  const SimKeys& k = simPanelKeys();
  if (k.faceDown) { *ax = 0.f; *ay = 0.f; *az = -0.95f; return; }
  if (k.shake) {
    // Big lateral spike — fakes shake detector trigger.
    float t = (float)millis() * 0.06f;
    *ax = 1.6f * (((int)t) & 1 ? 1.f : -1.f);
    *ay = 0.5f;
    *az = 0.6f;
    return;
  }
  *ax = 0.02f;
  *ay = 0.01f;
  *az = 0.98f;
}

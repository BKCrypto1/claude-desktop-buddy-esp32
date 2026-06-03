#include "hw/power.h"
#include "sim_panel.h"
#include <XPowersLib.h>

static XPowersPMU s_pmu;

bool hwPowerInit() { return true; }
void hwPowerOff() { /* no-op in sim */ }
bool hwAxpPekeyShortPress() { return false; }
bool hwAxpPekeyLongPress()  { return false; }
XPowersPMU* hwPmuRef() { return &s_pmu; }

HwBattery hwBattery() {
  HwBattery b{};
  b.mV  = 4012;
  b.mA  = -120;       // charging
  b.pct = 87;
  b.usbPresent = !simPanelKeys().usbToggle;   // U toggles unplug
  b.charging   = b.usbPresent;
  b.tempC      = 28;
  return b;
}

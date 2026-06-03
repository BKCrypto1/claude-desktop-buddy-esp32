#include "hw/border.h"

extern "C" void hwBorderAlertSetInternal(bool on);   // implemented in hw_display_sim.cpp

void hwBorderAlert(bool on) { hwBorderAlertSetInternal(on); }

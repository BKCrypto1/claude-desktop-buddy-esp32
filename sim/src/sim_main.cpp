// Desktop simulator entry point.
//
// On real ESP32 the Arduino runtime calls setup() once then loop()
// forever. We do the same here, sandwiching loop() between SDL event
// pumps so the OS gets to deliver mouse / keyboard / window-close
// events. Closing the window or hitting Esc cleanly exits.

#include "sim_panel.h"
#include <cstdio>
#include <cstdlib>
#include <cstdint>

extern void setup();
extern void loop();

int main(int /*argc*/, char** /*argv*/) {
  if (!simPanelInit("Claude Buddy Sim — ESP32-S3 2.16\"")) {
    std::fprintf(stderr, "sim: SDL init failed\n");
    return 1;
  }
  setup();
  while (true) {
    if (!simPanelPumpEvents()) break;
    loop();
  }
  simPanelShutdown();
  return 0;
}

#pragma once
// Stub of XPowersLib for the desktop simulator. Real lib drives an AXP2101
// PMU via I2C — sim has no PMU, so every method is a benign no-op or returns
// a sane default. hw_power_sim.cpp owns the visible "battery" state.

#include <cstdint>

class XPowersPMU {
public:
  bool isVbusIn() const               { return true; }   // sim is "USB connected" by default
  bool isCharging() const             { return false; }
  uint16_t getBattVoltage() const     { return 4012; }   // mV
  uint16_t getVbusVoltage() const     { return 5000; }   // mV
  uint16_t getSystemVoltage() const   { return 5000; }
  int getBatteryPercent() const       { return 87; }
  float getTemperature() const        { return 30.0f; }
  void  shutdown() {}

  // Rail / LDO controls referenced by hwInit() and friends.
  void enableALDO1() {}    void disableALDO1() {}
  void enableALDO2() {}    void disableALDO2() {}
  void enableALDO3() {}    void disableALDO3() {}
  void enableALDO4() {}    void disableALDO4() {}
  void enableBLDO1() {}    void disableBLDO1() {}
  void enableBLDO2() {}    void disableBLDO2() {}
  void enableDLDO1() {}    void disableDLDO1() {}
  void enableDLDO2() {}    void disableDLDO2() {}
  void setALDO1Voltage(int) {}
  void setALDO2Voltage(int) {}
  void setALDO3Voltage(int) {}
  void setALDO4Voltage(int) {}
  void setBLDO1Voltage(int) {}
  void setBLDO2Voltage(int) {}
  void setDLDO1Voltage(int) {}
  void setDLDO2Voltage(int) {}

  void clearIrqStatus() {}
  uint64_t getIrqStatus() { return 0; }
  void disableInterrupt(uint32_t) {}
  void enableInterrupt(uint32_t) {}
  bool init(int /*sda*/ = 0, int /*scl*/ = 0, int /*addr*/ = 0) { return true; }
};

// IRQ flag enum-ish constants the firmware references.
#define XPOWERS_USB_INSERT_INT     (1ULL << 0)
#define XPOWERS_USB_REMOVE_INT     (1ULL << 1)
#define XPOWERS_BAT_INSERT_INT     (1ULL << 2)
#define XPOWERS_BAT_REMOVE_INT     (1ULL << 3)
#define XPOWERS_PWR_BTN_PRESS_INT  (1ULL << 4)
#define XPOWERS_PWR_BTN_LONG_INT   (1ULL << 5)
#define XPOWERS_ALL_INT            ((uint64_t)-1)

# Desktop simulator Makefile.
#
# Builds the firmware-side .cpp files (board-agnostic plus all buddies)
# together with the sim/ shims into a single macOS executable that
# previews the ESP32-S3-Touch-AMOLED-2.16 board behaviour.
#
# Usage:
#   make            # build sim/build/buddy-sim
#   make run        # build and launch
#   make clean      # remove sim/build/

ROOT       := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
SIM_DIR    := $(ROOT)/sim
SRC_DIR    := $(ROOT)/src
BUILD_DIR  := $(SIM_DIR)/build
BIN        := $(BUILD_DIR)/buddy-sim

CXX        ?= clang++
CC         ?= clang

# SDL2 — uses Homebrew sdl2-config if present.
SDL_CFLAGS := $(shell sdl2-config --cflags 2>/dev/null)
SDL_LIBS   := $(shell sdl2-config --libs   2>/dev/null)

INCLUDES   := -I$(SIM_DIR)/include \
              -I$(SIM_DIR)/src \
              -I$(SIM_DIR)/vendor \
              -I$(SRC_DIR)

DEFINES    := -DSIM_HOST \
              -DBOARD_WAVESHARE_ESP32S3_TOUCH_AMOLED_2_16 \
              -DBOARD_HAS_PSRAM \
              -DXPOWERS_CHIP_AXP2101 \
              -DU8G2_USE_LARGE_FONTS \
              -DU8G2_FONT_SUPPORT \
              -DARDUINOJSON_ENABLE_STD_STREAM=1

CXXFLAGS   := -std=c++17 -O0 -g -MMD -MP -Wall -Wno-unused-parameter -Wno-unused-variable \
              -Wno-unused-function -Wno-sign-compare -Wno-deprecated-declarations \
              $(DEFINES) $(INCLUDES) $(SDL_CFLAGS)
CFLAGS     := -std=c11 -O0 -g -MMD -MP $(DEFINES) $(INCLUDES)
LDFLAGS    := $(SDL_LIBS)

# Firmware sources we keep (board-agnostic + all 18 buddies).
FW_CPP_KEEP := $(SRC_DIR)/main.cpp \
               $(SRC_DIR)/buddy.cpp \
               $(SRC_DIR)/character.cpp \
               $(wildcard $(SRC_DIR)/buddies/*.cpp)

# Sim sources — replaces every src/hw/*.cpp + ble_bridge.cpp.
SIM_CPP    := $(wildcard $(SIM_DIR)/src/*.cpp)
SIM_C      := $(wildcard $(SIM_DIR)/src/*.c)

# Vendored bitbank2 AnimatedGIF — host-portable, no asm references.
VENDOR_CPP := $(SIM_DIR)/vendor/AnimatedGIF/AnimatedGIF.cpp

ALL_CPP    := $(FW_CPP_KEEP) $(SIM_CPP) $(VENDOR_CPP)
ALL_C      := $(SIM_C)

OBJS_CPP   := $(patsubst $(ROOT)/%.cpp,$(BUILD_DIR)/%.o,$(ALL_CPP))
OBJS_C     := $(patsubst $(ROOT)/%.c,$(BUILD_DIR)/%.o,$(ALL_C))
OBJS       := $(OBJS_CPP) $(OBJS_C)

.PHONY: all run clean
all: $(BIN)

Q := @
$(BIN): $(OBJS)
	$(Q)mkdir -p $(@D)
	$(Q)echo "  LD  $(@F)"
	$(Q)$(CXX) $^ -o $@ $(LDFLAGS)

$(BUILD_DIR)/%.o: $(ROOT)/%.cpp
	$(Q)mkdir -p $(@D)
	$(Q)echo "  CXX $(<F)"
	$(Q)$(CXX) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/%.o: $(ROOT)/%.c
	$(Q)mkdir -p $(@D)
	$(Q)echo "  CC  $(<F)"
	$(Q)$(CC) $(CFLAGS) -c $< -o $@

run: $(BIN)
	$(BIN)

clean:
	rm -rf $(BUILD_DIR)

# Pull in -MMD-generated header deps so changing a .h triggers a rebuild
# of every .o that included it. Without this the AnimatedGIF shim swap
# silently used cached object files. -include suppresses missing-file
# errors for the first build.
-include $(OBJS:.o=.d)

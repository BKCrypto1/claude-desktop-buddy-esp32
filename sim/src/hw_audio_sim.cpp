#include "hw/audio.h"
#include <cstdio>

bool hwAudioInit() { return true; }
void hwBeep(uint16_t /*freqHz*/, uint16_t /*durMs*/) { /* silent */ }

// Wiring only: HAL (M5 implementation) + ApprovalApp.
// Excluded from the native test env (native builds test/ only).
#ifdef ARDUINO
#include <Arduino.h>

void setup() {}
void loop() {}
#endif

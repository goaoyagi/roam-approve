// Copy to config.h (gitignored) and fill in real values.
#pragma once

#ifndef WIFI_SSID
#define WIFI_SSID "your-wifi-ssid"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "your-wifi-password"
#endif
#ifndef MQTT_HOST
#define MQTT_HOST "192.168.x.x"
#endif
#ifndef MQTT_PORT
#define MQTT_PORT 1883
#endif
#ifndef BRIDGE_URL
#define BRIDGE_URL "http://192.168.x.x:8000"
#endif
#ifndef DEVICE_TOKEN
#define DEVICE_TOKEN "changeme-run-make-gen-tokens"
#endif

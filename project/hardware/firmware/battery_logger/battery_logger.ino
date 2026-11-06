/*
  Battery Lifecycle Analytics: bench battery monitoring board (future hardware option)

  Board   : ESP32 DevKit (ESP32-WROOM-32)
  Sensors : INA219 current/voltage monitor (I2C, bidirectional, 0.1 ohm shunt)
            DS18B20 temperature probe taped to the cell (OneWire)
  Control : GPIO 26 -> logic-level MOSFET (IRLZ44N) switching a 3.9 ohm / 10 W load resistor (about 1 A discharge)
            GPIO 27 -> charger enable (TP4056 module CE pin, or a relay in the charger's input)
  Output  : one JSON line per second on USB serial, 115200 baud. Format in batterylife/hardware/protocol.py:
            {"dev":"BLM-01","cell":"HW-001","t_ms":123456,"v":3.912,"i":-0.998,"temp":27.4,"phase":"discharge"}

  Libraries (Arduino Library Manager): Adafruit INA219, OneWire, DallasTemperature

  Cycle logic (runs unattended):
    CHARGE    charger on, load off   -> until current < 0.05 A at 4.2 V (charger's CV cut-off)
    REST      both off, 5 min
    DISCHARGE load on                -> until voltage <= 2.80 V
    REST      both off, 5 min, then repeat
  SAFETY: hard stop on V > 4.25 V, V < 2.50 V or T > 55 C (both paths switched off, phase "fault").
          Use a protected cell or a protection board, never leave it unattended without a fire-safe container.
*/
#include <Wire.h>
#include <Adafruit_INA219.h>
#include <OneWire.h>
#include <DallasTemperature.h>

const char* DEVICE_ID = "BLM-01";
const char* CELL_ID   = "HW-001";
const int PIN_LOAD    = 26;
const int PIN_CHARGE  = 27;
const int PIN_ONEWIRE = 4;
const unsigned long SAMPLE_MS = 1000;
const unsigned long REST_MS   = 5UL * 60UL * 1000UL;

const float V_FULL = 4.18, I_CUTOFF = 0.05, V_EMPTY = 2.80;
const float V_ABS_MAX = 4.25, V_ABS_MIN = 2.50, T_MAX = 55.0;

Adafruit_INA219 ina;
OneWire oneWire(PIN_ONEWIRE);
DallasTemperature probe(&oneWire);

enum Phase { CHARGE, REST_AFTER_CHARGE, DISCHARGE, REST_AFTER_DISCHARGE, FAULT };
Phase phase = CHARGE;
unsigned long phaseStart = 0, lastSample = 0;

const char* phaseName(Phase p) {
  switch (p) {
    case CHARGE: return "charge";
    case DISCHARGE: return "discharge";
    case FAULT: return "fault";
    default: return "rest";
  }
}

void setOutputs(bool charge, bool load) {
  digitalWrite(PIN_LOAD, LOW);            // never both on: switch off first
  digitalWrite(PIN_CHARGE, LOW);
  delay(5);
  digitalWrite(PIN_CHARGE, charge ? HIGH : LOW);
  digitalWrite(PIN_LOAD, load ? HIGH : LOW);
}

void enter(Phase p) {
  phase = p;
  phaseStart = millis();
  setOutputs(p == CHARGE, p == DISCHARGE);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LOAD, OUTPUT);
  pinMode(PIN_CHARGE, OUTPUT);
  setOutputs(false, false);
  if (!ina.begin()) {
    Serial.println("{\"error\":\"INA219 not found\"}");
    while (true) delay(1000);
  }
  ina.setCalibration_16V_400mA();          // replace with a 2 A calibration for a 0.1 ohm shunt (see docs/hardware.md)
  probe.begin();
  enter(CHARGE);
}

void loop() {
  if (millis() - lastSample < SAMPLE_MS) return;
  lastSample = millis();

  float v = ina.getBusVoltage_V() + ina.getShuntVoltage_mV() / 1000.0;   // cell terminal voltage
  float i = ina.getCurrent_mA() / 1000.0;                                 // + charging, - discharging (wire shunt accordingly)
  probe.requestTemperatures();
  float t = probe.getTempCByIndex(0);

  if (phase != FAULT && (v > V_ABS_MAX || v < V_ABS_MIN || t > T_MAX)) enter(FAULT);

  unsigned long inPhase = millis() - phaseStart;
  switch (phase) {
    case CHARGE:               if (v >= V_FULL && i < I_CUTOFF && inPhase > 60000) enter(REST_AFTER_CHARGE); break;
    case REST_AFTER_CHARGE:    if (inPhase >= REST_MS) enter(DISCHARGE); break;
    case DISCHARGE:            if (v <= V_EMPTY) enter(REST_AFTER_DISCHARGE); break;
    case REST_AFTER_DISCHARGE: if (inPhase >= REST_MS) enter(CHARGE); break;
    case FAULT:                setOutputs(false, false); break;
  }

  Serial.printf("{\"dev\":\"%s\",\"cell\":\"%s\",\"t_ms\":%lu,\"v\":%.4f,\"i\":%.4f,\"temp\":%.2f,\"phase\":\"%s\"}\n",
                DEVICE_ID, CELL_ID, millis(), v, i, t, phaseName(phase));
}

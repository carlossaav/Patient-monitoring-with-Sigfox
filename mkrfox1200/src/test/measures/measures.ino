/*
 *   Every Sketch that uses the PulseSensor Playground must
 *   define USE_ARDUINO_INTERRUPTS before including PulseSensorPlayground.h.
 *   Here, #define USE_ARDUINO_INTERRUPTS false tells the library to
 *   not use interrupts to read data from the PulseSensor.
 * 
 *   If you want to use interrupts, simply change the line below
 *   to read:
 *     #define USE_ARDUINO_INTERRUPTS true
 * 
 *   Set US_PS_INTERRUPTS to false if either
 *   1) Your Arduino platform's interrupts aren't yet supported
 *   by PulseSensor Playground, or
 *   2) You don't wish to use interrupts because of the side effects.
 * 
 *   NOTE: if US_PS_INTERRUPTS is false, your Sketch must
 *   call pulse.sawNewSample() at least once every 2 milliseconds
 *   to accurately read the PulseSensor signal.
 */

#define USE_ARDUINO_INTERRUPTS false  // Set-up low-level interrupts for most acurate BPM math.
// #define US_PS_INTERRUPTS false

#include <PulseSensorPlayground.h>
#include <RTCZero.h>
#include <SigFox.h>
#include <Wire.h>
#include <Protocentral_MAX30205.h>

#define PULSE_PIN 0                // PulseSensor WIRE connected to ANALOG PIN 0
#define INPUT_BUTTON_PIN 5         // DIGITAL PIN 5 USED TO INTERRUPT whenever the button is pressed
#define HEARTBEAT_LED LED_BUILTIN  // Blinks with every heartbeat.
#define LIMIT_EXCEEDED_LED 7       // Blinks whenever a bpm limit exceeded occurs
#define EMERGENCY_LED 8            // Used on emergencies

#define PULSE_THRESHOLD 2150  // Determine which Signal to "count as a beat" and which to ignore

#define UPPER_BPM_LIMIT 135
#define LOWER_BPM_LIMIT 55
#define UPPER_IBI_LIMIT 1000
#define LOWER_IBI_LIMIT 500
#define UPPER_TEMP_LIMIT 37.5
#define LOWER_TEMP_LIMIT 35.5

// keep HEARTBEAT_LED 3000 milliseconds set to LOW && HIGH on error
#define BUG_FLASH 3000

#define ROUND_DURATION 60000
#define INTERVAL_DURATION 730000

#define ROUND_FIELD 0
#define INTERVAL_FIELD 1

#define MAX_ROUNDS 30

/** Variables **/

struct sum {
  unsigned int rsum;
  unsigned int isum;
};

struct sum sum_bpm, sum_ibi;


struct range {
  int rcount;  // Times bpm value fell within the range on the round
  int icount;  // Times bpm value fell within the range in whole interval
};

byte range_top; // Determined by ranges width
byte ubpm_lim = UPPER_BPM_LIMIT;
byte lbpm_lim = LOWER_BPM_LIMIT;

/* To later process where bpm readings have been falling across the interval, 
 * we'll define a set of BPM Ranges:
 * ranges[0] stores bpm reading counts in range [0, lbpm_lim-1]
 * ranges[1] stores bpm reading counts in range [lbpm_lim, range_top]
 * ranges[2] stores bpm reading counts in range [range_top+1, ubpm_lim]
 * ranges[3] stores bpm reading counts in range [ubpm_lim+1, infinite]
 */
struct range ranges[4];

unsigned int last_count = 0;
unsigned int bpm_ibi_sample_counter = 0;  // count bpm and ibi readings
unsigned long limits_exceeded_counter = 0;


// Alarm Button purposes
volatile byte button_flag = 0;
byte button_pushed = 0;


int iround = 0;  // Round we are in
unsigned long tstamp = 0;

int max_bpm_arr[MAX_ROUNDS];
int min_bpm_arr[MAX_ROUNDS];
int max_ibi_arr[MAX_ROUNDS];
int min_ibi_arr[MAX_ROUNDS];

byte max_bpm_round = 0, max_bpm = 0;
byte min_bpm_round = 255, min_bpm = 255;

int max_ibi_round = 0, max_ibi = 0;
int min_ibi_round = 20000, min_ibi = 20000;


PulseSensorPlayground pulseSensor;
RTCZero rtc;
MAX30205 tempSensor;

void setup() {

  Serial.begin(9600);
  while (!Serial);

  Wire.begin();

  pinMode(INPUT_BUTTON_PIN, INPUT_PULLUP);  // button press
  pinMode(HEARTBEAT_LED, OUTPUT);
  pinMode(LIMIT_EXCEEDED_LED, OUTPUT);
  pinMode(EMERGENCY_LED, OUTPUT);

  analogReadResolution(12);

  digitalWrite(HEARTBEAT_LED, LOW);
  digitalWrite(LIMIT_EXCEEDED_LED, LOW);
  digitalWrite(EMERGENCY_LED, LOW);
  attachInterrupt(digitalPinToInterrupt(INPUT_BUTTON_PIN), button_pressed, FALLING);

  // Configure the PulseSensor object
  pulseSensor.analogInput(PULSE_PIN);
  pulseSensor.blinkOnPulse(HEARTBEAT_LED);  // blink HEARTBEAT_LED with every heartbeat
  pulseSensor.setThreshold(PULSE_THRESHOLD);

  if (pulseSensor.begin())
    Serial.println("We created a Pulsesensor Object !");
  else {
    Serial.println("Problems to start reading PulseSensor");
    while (1)
      flash_led(HEARTBEAT_LED);
  }

  while (!tempSensor.scanAvailableSensors()) {
    Serial.println("Couldn't find the temperature sensor, please connect the sensor.");
    delay(30000);
  }

  set_range_top();

  Serial.print("First range: <"); Serial.println(lbpm_lim);
  Serial.print("Second range: ["); Serial.print(lbpm_lim);
  Serial.print(", "); Serial.print(range_top); Serial.println("]");
  Serial.print("Third range: ["); Serial.print(range_top+1);
  Serial.print(", "); Serial.print(ubpm_lim); Serial.println("]");
  Serial.print("Higher range: >"); Serial.println(ubpm_lim);

  for (int i = 0; i < (sizeof(ranges) / sizeof(ranges[0])); i++) {
    ranges[i].rcount = 0;
    ranges[i].icount = 0;
  }

  for (int i = 0; i < MAX_ROUNDS; i++) {
    max_bpm_arr[i] = -1;
    min_bpm_arr[i] = -1;
    max_ibi_arr[i] = -1;
    min_ibi_arr[i] = -1;
  }


  sum_bpm.rsum = 0;
  sum_bpm.isum = 0;
  sum_ibi.rsum = 0;
  sum_ibi.isum = 0;

  rtc.begin();
  rtc.setTime(16, 30, 00);
  rtc.setDate(14, 4, 23);
}

// Flash led to show things didn't work.
void flash_led(int led) {
  digitalWrite(led, LOW);
  delay(BUG_FLASH);
  digitalWrite(led, HIGH);
  delay(BUG_FLASH);
}

void set_range_top() {
  byte aux = (byte)floor((UPPER_BPM_LIMIT - lbpm_lim)/2);
  range_top = lbpm_lim + aux;
  if (((ubpm_lim - lbpm_lim) % 2) == 0) // even number
    range_top--;
}

void get_temperature() {

  rtc.disableAlarm();
  Serial.println("Reading temperatures...");

  if (!SigFox.begin()) {
    Serial.println("Sigfox failure");
    return;
  }

  Serial.println();
  Serial.print("Sigfox Module internal temperature: ");
  Serial.print(SigFox.internalTemperature());
  SigFox.end();
  Serial.println(" ªC");
  Serial.println();

  tempSensor.begin();
  Serial.print("Protocentral sensor reading: ");
  Serial.print(tempSensor.getTemperature());
  Serial.println(" ªC");
  tempSensor.shutdown();
  Serial.println();
  Serial.print("Next update on ");
  Serial.print(((float)ROUND_DURATION / 1000.0) + 5.0);
  Serial.println(" seconds.");
  Serial.println();
  Serial.println();
}

void print_avgs(unsigned int nsamples, byte sum_field) {

  unsigned int sum_bpm_value, sum_ibi_value;

  /* Get sum_bpm and sum_ibi fields from sum struct */

  if (sum_field == ROUND_FIELD) {
    sum_bpm_value = sum_bpm.rsum;
    sum_ibi_value = sum_ibi.rsum;
  } else {  // sum_field == INTERVAL_FIELD
    sum_bpm_value = sum_bpm.isum;
    sum_ibi_value = sum_ibi.isum;
  }

  Serial.print("Average bpm = ");
  Serial.println(round((float)sum_bpm_value / (float)nsamples));
  Serial.print("Average ibi = ");
  Serial.println(round((float)sum_ibi_value / (float)nsamples));
  Serial.println();
}

void print_ranges(unsigned int nsamples, byte range_field) {

  int rvalue;
  int max_value = -1;
  int max_range_ids[3] = { -1, -1, -1 };
  byte match, match_count, counter = 0;

  // We want to save the indexes of the three highest values of ranges[] on max_range_ids[]
  match = 0;
  match_count = 0;
  while (counter != 3) {
    byte skipped = 0;
    for (int i = 0; i < (sizeof(ranges) / sizeof(ranges[0])); i++) {
      if (counter != 0) {
        if (match == 0) {
          for (int j = 0; j < counter; j++) {
            if (i == max_range_ids[j]) {
              match = 1;
              match_count++;
              break;
            }
          }
        }
        if (!skipped && match) {  // counter != 0
          if (counter == 1) skipped = 1;
          else  // counter==2
            if (match_count < 2) match = 0;
            else skipped = 1;
          continue;
        }
      }

      if (range_field == ROUND_FIELD) rvalue = ranges[i].rcount;
      else rvalue = ranges[i].icount;

      if (rvalue > max_value) {
        max_value = rvalue;
        max_range_ids[counter] = i;
      }
    }
    match = 0;
    match_count = 0;
    skipped = 0;
    max_value = -1;
    counter++;
  }

  /* Calculate percentages */

  for (int i = 0, j; i < (sizeof(max_range_ids) / sizeof(max_range_ids[0])); i++) {
    j = max_range_ids[i];
    if (j>=0 && j<=3) {
      Serial.print("ranges[");
      Serial.print(j);
      Serial.print("] (Range [");
    }
    switch (j) {
      case 0:
        Serial.print("0, "); Serial.print(lbpm_lim-1);
        break;
      case 1:
        Serial.print(lbpm_lim); Serial.print(", ");
        Serial.print(range_top);
        break;
      case 2:
        Serial.print(range_top+1); Serial.print(", ");
        Serial.print(ubpm_lim);
        break;
      case 3:
        Serial.print(ubpm_lim+1); Serial.print(", infinite");
        break;
      default:
        Serial.println("Avoid computing percentages...");
        Serial.println();
        continue;
    }
    
    if (j>=0 && j<=3)
      Serial.print("] BPM): ");

    if (range_field == ROUND_FIELD) rvalue = ranges[j].rcount;
    else rvalue = ranges[j].icount;

    Serial.print(round(((float)rvalue / (float)nsamples) * 100.0));
    Serial.print("%");
    Serial.println();
  }
  Serial.println();
}

/* Interrupt Service Routine button_pressed(),
 * triggered whenever the user pushes the emergency button
 */
void button_pressed() {
  button_flag = 1;
}

void handle_button_pushed() {
  if (button_pushed) {
    button_pushed = 0;
    Serial.println("Emergency deactivated.");
    Serial.println();
    digitalWrite(EMERGENCY_LED, LOW);
    return;
  }
  button_pushed = 1;
  Serial.println("Emergency activated!");
  Serial.println();
  digitalWrite(EMERGENCY_LED, HIGH);
}

/* Overloaded function series to check if any 
 * limit has been exceeded */

byte check_upper_limit(byte bpm) {
  return (bpm > UPPER_BPM_LIMIT);
}

byte check_lower_limit(byte bpm) {
  return (bpm < LOWER_BPM_LIMIT);
}

byte check_upper_limit(int ibi) {
  return (ibi > UPPER_IBI_LIMIT);
}

byte check_lower_limit(int ibi) {
  return (ibi < LOWER_IBI_LIMIT);
}

byte bytecast(int value) {
  if (value < 0)
    return (byte)0;
  else if (value > 255)
    return (byte)255;
  return byte(value);
}

void increase_range(byte index) {
  if (index>=0 && index<(sizeof(ranges)/sizeof(ranges[0]))) {
    ranges[index].rcount++;
    ranges[index].icount++;
  }
  else Serial.println("Index out of range");
}

void loop() {

  int ibi;
  byte bpm, limit;
  unsigned long duration;

  if (button_flag) {
    handle_button_pushed();
    button_flag = 0;
  }

  /* See if a sample is ready from the PulseSensor.
   *
   * If USE_INTERRUPTS is true, the PulseSensor Playground
   * will automatically read and process samples from
   * the PulseSensor.
   *
   * If USE_INTERRUPTS is false, this call to sawNewSample()
   * will, if enough time has passed, read and process a
   * sample (analog voltage) from the PulseSensor. */

  if (pulseSensor.sawNewSample()) {

    limit = 0;
    digitalWrite(LIMIT_EXCEEDED_LED, LOW);

    bpm = bytecast(pulseSensor.getBeatsPerMinute());
    ibi = pulseSensor.getInterBeatIntervalMs();

    sum_bpm.rsum += bpm;
    sum_bpm.isum += bpm;
    sum_ibi.rsum += ibi;
    sum_ibi.isum += ibi;
    bpm_ibi_sample_counter++;

    if (bpm<lbpm_lim) increase_range(0);
    else if (bpm>=lbpm_lim && bpm<=range_top) increase_range(1);
    else if (bpm>=(range_top+1) && bpm<=ubpm_lim) increase_range(2);
    else increase_range(3); // bpm > ubpm_lim

    if (bpm > max_bpm_round)
      max_bpm_round = bpm;
    else if (bpm < min_bpm_round)
      min_bpm_round = bpm;

    if (ibi > max_ibi_round)
      max_ibi_round = ibi;
    else if (ibi < min_ibi_round)
      min_ibi_round = ibi;


    /* Double checking match relies on values set by constants UPPER_BPM_LIMIT, etc.
     * i.e. even if only one measure limit is exceeded, it's likely that the other
     * measurment of the pair also does (max_bpm-min_ibi, min_bpm-max_ibi). */

    if (check_upper_limit(bpm)) {
      limits_exceeded_counter++;
      limit = 1;
      /* Serial.print("Upper Bpm Limit exceeded. Bpm = "); Serial.println(bpm);
      if (check_lower_limit(ibi)) {
        Serial.println("Last upper bpm and lower ibi exceeded limits were coupled");
        Serial.print("Ibi = "); Serial.println(ibi);
      }
      */
    } else {
      if (check_lower_limit(bpm)) {
        limits_exceeded_counter++;
        limit = 1;
        /* Serial.print("Lower Bpm Limit exceeded. Bpm = "); Serial.println(bpm);
        if (check_upper_limit(ibi)) {
          Serial.println("Last lower bpm and upper ibi exceeded limits were coupled");
          Serial.print("Ibi = "); Serial.println(ibi);
        }
      */
      }
    }

    if (limit) digitalWrite(LIMIT_EXCEEDED_LED, HIGH);
  }

  if ((duration = (millis() - tstamp)) >= ROUND_DURATION) {

    unsigned int nsamples;

    digitalWrite(LIMIT_EXCEEDED_LED, LOW);

    nsamples = bpm_ibi_sample_counter - last_count;
    last_count = bpm_ibi_sample_counter;

    Serial.print("ROUND: ");
    Serial.println(iround);
    Serial.println();
    Serial.print("Program started ");
    Serial.print((float)millis() / 1000.0, 2);
    Serial.println(" seconds ago.");
    Serial.println();
    Serial.println();

    Serial.print("We've got up to ");
    Serial.print(nsamples);
    Serial.print(" samples in ");
    Serial.print((float)duration / 1000.0, 2);
    Serial.print(" seconds");
    Serial.println();

    Serial.print("bpm_ibi_sample_counter = ");
    Serial.println(bpm_ibi_sample_counter);
    Serial.print("limits_exceeded_counter = ");
    Serial.println(limits_exceeded_counter);
    Serial.println();

    Serial.print("max_bpm_round = ");
    Serial.println(max_bpm_round);
    Serial.print("min_bpm_round = ");
    Serial.println(min_bpm_round);
    Serial.println();
    Serial.print("max_ibi_round = ");
    Serial.println(max_ibi_round);
    Serial.print("min_ibi_round = ");
    Serial.println(min_ibi_round);
    Serial.println();
    Serial.println();

    if (max_bpm_round > max_bpm)
      max_bpm = max_bpm_round;
    if (max_ibi_round > max_ibi)
      max_ibi = max_ibi_round;
    if (min_bpm_round < min_bpm)
      min_bpm = min_bpm_round;
    if (min_ibi_round < min_ibi)
      min_ibi = min_ibi_round;

    max_bpm_arr[iround] = max_bpm_round;
    min_bpm_arr[iround] = min_bpm_round;
    max_ibi_arr[iround] = max_ibi_round;
    min_ibi_arr[iround] = min_ibi_round;

    iround++;

    max_bpm_round = 0;
    min_bpm_round = 255;
    max_ibi_round = 0;
    min_ibi_round = 20000;

    /* Compute and report measurements... */

    if (bpm_ibi_sample_counter != 0) {  // (Avoid division by zero on runtime!)
      print_avgs(nsamples, ROUND_FIELD);
      print_ranges(nsamples, ROUND_FIELD);
    } else Serial.println("No samples on the box!");


    /* Reset round counters and additions */
    sum_bpm.rsum = 0;
    sum_ibi.rsum = 0;
    for (int i = 0; i < (sizeof(ranges) / sizeof(ranges[0])); i++)
      ranges[i].rcount = 0;


    if (millis() >= INTERVAL_DURATION) {
      Serial.print("This program has been running for ");
      Serial.print(((float)millis() / 1000.0) / 60.0, 2);
      Serial.println(" minutes");
      // Serial.print("(millis()/1000)/60 (minutes) = "); Serial.println((millis()/1000)/60.0);
      Serial.println();

      Serial.println("HISTORY OF MAXS AND MINS");
      Serial.println();

      Serial.print("MAXS BPM ROUNDS: [");
      if (max_bpm_arr[0] != -1) {
        Serial.print(max_bpm_arr[0]);
        for (int i = 1; i < MAX_ROUNDS; i++) {
          if (max_bpm_arr[i] == -1)
            break;
          Serial.print(",");
          Serial.print(max_bpm_arr[i]);
        }
      }
      Serial.println("]");

      Serial.print("MINS BPM ROUNDS: [");

      if (min_bpm_arr[0] != -1) {
        Serial.print(min_bpm_arr[0]);
        for (int i = 1; i < MAX_ROUNDS; i++) {
          if (min_bpm_arr[i] == -1)
            break;
          Serial.print(",");
          Serial.print(min_bpm_arr[i]);
        }
      }
      Serial.println("]");

      Serial.print("MAXS IBI ROUNDS: [");
      if (max_ibi_arr[0] != -1) {
        Serial.print(max_ibi_arr[0]);
        for (int i = 1; i < MAX_ROUNDS; i++) {
          if (max_ibi_arr[i] == -1)
            break;
          Serial.print(",");
          Serial.print(max_ibi_arr[i]);
        }
      }
      Serial.println("]");

      Serial.print("MINS IBI ROUNDS: [");
      if (min_ibi_arr[0] != -1) {
        Serial.print(min_ibi_arr[0]);
        for (int i = 1; i < MAX_ROUNDS; i++) {
          if (min_ibi_arr[i] == -1)
            break;
          Serial.print(",");
          Serial.print(min_ibi_arr[i]);
        }
      }
      Serial.println("]");
      Serial.println();
      Serial.println();

      /* Compute and report measurements... */

      if (bpm_ibi_sample_counter != 0) {  // Avoid division by zero on runtime!
        print_avgs(bpm_ibi_sample_counter, INTERVAL_FIELD);
        print_ranges(bpm_ibi_sample_counter, INTERVAL_FIELD);

        Serial.print("Highest bpm value read (max_bpm) = ");
        Serial.println(max_bpm);
        Serial.print("Lowest bpm value read (min_bpm) = ");
        Serial.println(min_bpm);
        Serial.print("Highest ibi value read (max_ibi) = ");
        Serial.println(max_ibi);
        Serial.print("Lowest ibi value read (min_ibi) = ");
        Serial.println(min_ibi);
      } else Serial.println("No samples on the box!");

      Serial.println();
      Serial.println();
      Serial.print("Total limits exceeded (limits_exceeded_counter) = ");
      Serial.println(limits_exceeded_counter);
      Serial.println();
      Serial.print("Total Taken samples (bpm_ibi_sample_counter) = ");
      Serial.println(bpm_ibi_sample_counter);
      Serial.println("End of story. Bye bye.");
      rtc.standbyMode();
      while (1)
        ;
    }

    if (iround == MAX_ROUNDS) {
      Serial.println("We've got to maximum round. Restart the program to continue sampling.");
      while (1)
        ;
    }

    rtc.setAlarmSeconds((rtc.getSeconds() + 5) % 60);
    rtc.enableAlarm(rtc.MATCH_SS);
    rtc.attachInterrupt(get_temperature);
    Serial.println("Reading temperature in 5 seconds...");

    tstamp = millis();
  }
}

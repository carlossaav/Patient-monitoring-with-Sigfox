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

#define USE_ARDUINO_INTERRUPTS false // Set-up low-level interrupts for most acurate BPM math.
// #define US_PS_INTERRUPTS false


#include <PulseSensorPlayground.h>
#include <RTCZero.h>
#include <SigFox.h>
#include <Wire.h>
#include <Protocentral_MAX30205.h>


#define PULSE_PIN 0           // PulseSensor WIRE connected to ANALOG PIN 0
#define INPUT_BUTTON_PIN 5    // DIGITAL PIN 5 USED TO INTERRUPT whenever the button is pressed
#define PULSESENSOR_LED 6     // Blinks with every heartbeat
#define EMERGENCY_LED 8       // Used on emergencies

#define PULSE_THRESHOLD 2140  // Determine which Signal to "count as a beat" and which to ignore                               


#define UPPER_BPM_LIMIT 120
#define LOWER_BPM_LIMIT 60
#define UPPER_IBI_LIMIT 1000
#define LOWER_IBI_LIMIT 500
#define UPPER_TEMP_LIMIT 37.5
#define LOWER_TEMP_LIMIT 35.5


#define MAX_BPM_SAMPLES 600
#define MAX_IBI_SAMPLES 600


// keep the LED_BUILTIN||PULSESENSOR_LED 3000 milliseconds set to LOW && HIGH on error
#define BUG_FLASH 3000


/** Variables **/

/* measurements to send
byte max_bpm, min_bpm;
int max_ibi, min_ibi;
float avg_bpm, avg_ibi, sd_bpm, sd_ibi;
*/

/* sampling buffers */
byte bpm_hist[MAX_BPM_SAMPLES];
int ibi_hist[MAX_IBI_SAMPLES];


// sample counter
unsigned long bpm_ibi_sample_counter;


// Alarm Button purposes
volatile byte button_flag = 0;
byte button_pushed = 0;


byte bpm;
int test_index = 0;
int ibi, seconds;
unsigned long tstamp = 0;

int max_bpm_arr[30];
int min_bpm_arr[30];
int max_ibi_arr[30];
int min_ibi_arr[30];

byte max_bpm_loop_round = 0;
byte max_bpm_loop = 0;
int max_ibi_loop_round = 0;
int max_ibi_loop = 0;

byte min_bpm_loop_round = 255;
byte min_bpm_loop = 255;
int min_ibi_loop_round = 5000;
int min_ibi_loop = 5000;


PulseSensorPlayground pulseSensor;
RTCZero rtc;
MAX30205 tempSensor;


void setup() {

  Serial.begin(9600);
  while (!Serial) ;
  
  for (int i=0; i<30; i++) {
    max_bpm_arr[i] = -1;
    min_bpm_arr[i] = -1;
    max_ibi_arr[i] = -1;
    min_ibi_arr[i] = -1;
  }


  pinMode(INPUT_BUTTON_PIN, INPUT_PULLUP); // button press
  pinMode(PULSESENSOR_LED, OUTPUT);
  pinMode(EMERGENCY_LED, OUTPUT);
  
  analogReadResolution(12);

  digitalWrite(EMERGENCY_LED, LOW);
  attachInterrupt(digitalPinToInterrupt(INPUT_BUTTON_PIN), button_pressed, FALLING);

  // Configure the PulseSensor object, by assigning our variables to it
  pulseSensor.analogInput(PULSE_PIN);
  pulseSensor.blinkOnPulse(PULSESENSOR_LED);  // blink PULSESENSOR_LED with every heartbeat
  pulseSensor.setThreshold(PULSE_THRESHOLD);

  if (pulseSensor.begin())
    Serial.println("We created a pulseSensor Object !");
  else {
    Serial.println("Problems to start reading PulseSensor");
    while (1)
      flash_led(PULSESENSOR_LED);
  }

  Wire.begin();

  while(!tempSensor.scanAvailableSensors()){
    Serial.println("Couldn't find the temperature sensor, please connect the sensor." );
    delay(30000);
  }

  rtc.begin();
  rtc.setTime(13, 00, 00);
  rtc.setDate(20, 5, 20);
}


// Flash led to show things didn't work.
void flash_led(int led) {
  digitalWrite(led, LOW);
  delay(BUG_FLASH);
  digitalWrite(led, HIGH);
  delay(BUG_FLASH);
}


void get_temperature() {

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
  Serial.println("Next update on 30 seconds.");
  rtc.disableAlarm();
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
    digitalWrite(EMERGENCY_LED, LOW);
    return;
  }
  button_pushed = 1;
  Serial.println("Emergency activated!");
  digitalWrite(EMERGENCY_LED, HIGH);
}


/* Overloaded function series to check if any 
 * limit has been exceeded
 */
byte check_upper_limit(float temperature) {
  return (temperature > UPPER_TEMP_LIMIT);
}

byte check_upper_limit(byte bpm) {
  return (bpm > UPPER_BPM_LIMIT);
}

byte check_upper_limit(int ibi) {
  return (ibi > UPPER_IBI_LIMIT);
}

byte check_lower_limit(float temperature) {
  return (temperature < LOWER_TEMP_LIMIT);
}

byte check_lower_limit(byte bpm) {
  return (bpm < LOWER_BPM_LIMIT);
}

byte check_lower_limit(int ibi) {
  return (ibi < LOWER_IBI_LIMIT);
}



byte bytecast(int bpm) {
  if (bpm<0)
    return 0;
  else
    if (bpm>255)
      return 255;
  return byte(bpm);
}

void loop() {

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
   * sample (analog voltage) from the PulseSensor.
   */

  if (pulseSensor.sawNewSample()) {
    // reduce sampling (32kb SRAM)
    bpm = bytecast(pulseSensor.getBeatsPerMinute());
    ibi = pulseSensor.getInterBeatIntervalMs();
//    bpm_hist[bpm_ibi_sample_counter] = bpm;
//    ibi_hist[bpm_ibi_sample_counter] = ibi;

    bpm_ibi_sample_counter++; // count bpm and ibi readings

    if (bpm > max_bpm_loop_round)
      max_bpm_loop_round = bpm;
    else
      if (bpm < min_bpm_loop_round)
        min_bpm_loop_round = bpm;

    if (ibi > max_ibi_loop_round)
      max_ibi_loop_round = ibi;
    else
      if (ibi < min_ibi_loop_round)
        min_ibi_loop_round = ibi;


   /* Aunque no salte aquí, probablemente estarán emparejados igualmente.
    * Esto depende de los valores que hayas puesto en las constantes UPPER_BPM_LIMIT, etc
    
    if ((check_upper_limit(bpm)) && (check_lower_limit(ibi))) {
      Serial.println();
      Serial.println("Last upper bpm and lower ibi exceeded limits were coupled");
      Serial.println();
    }
    else {
      if ((check_lower_limit(bpm)) && (check_upper_limit(ibi))) {
        Serial.println();
        Serial.println("Last lower bpm and upper ibi exceeded limits were coupled");
        Serial.println();
      }
    }
    */
  }

  if ((millis() - tstamp) > 35000) {
    tstamp = millis();
    Serial.println();
    Serial.println();
    Serial.println();
    Serial.print("ROUND: ");
    Serial.println(test_index);
    Serial.println();
    Serial.print("Program started ");
    Serial.print((millis())/1000);
    Serial.println(" seconds ago.");
    Serial.println();
    Serial.print("bpm_ibi_sample_counter = ");
    Serial.println(bpm_ibi_sample_counter);
    Serial.print("Highest bpm value read in this round = ");
    Serial.println(max_bpm_loop_round);
    Serial.print("Lowest bpm value read in this round = ");
    Serial.println(min_bpm_loop_round);
    Serial.println();
    Serial.print("Highest ibi value read in this round = ");
    Serial.println(max_ibi_loop_round);
    Serial.print("Lowest ibi value read in this round = ");
    Serial.println(min_ibi_loop_round);
    Serial.println();

    if (max_bpm_loop_round > max_bpm_loop)
      max_bpm_loop = max_bpm_loop_round;
    if (max_ibi_loop_round > max_ibi_loop)
      max_ibi_loop = max_ibi_loop_round;
    if (min_bpm_loop_round < min_bpm_loop)
      min_bpm_loop = min_bpm_loop_round;
    if (min_ibi_loop_round < min_ibi_loop)
      min_ibi_loop = min_ibi_loop_round;

    max_bpm_arr[test_index] = max_bpm_loop_round;
    min_bpm_arr[test_index] = min_bpm_loop_round;
    max_ibi_arr[test_index] = max_ibi_loop_round;
    min_ibi_arr[test_index] = min_ibi_loop_round;

    test_index++;

    max_bpm_loop_round = 0;
    min_bpm_loop_round = 255;
    max_ibi_loop_round = 0;
    min_ibi_loop_round = 5000;

    if (millis() > 730000) {
      Serial.println("This program has been running at least for 12 minutes.");
      Serial.print("millis() = ");
      Serial.println(millis());
      Serial.print("Total Taken samples (bpm_ibi_sample_counter) = ");
      Serial.println(bpm_ibi_sample_counter);

      Serial.println();
      Serial.println("HISTORY OF MAXS AND MINS");
      Serial.println();

      Serial.print("MAXS BPM ROUNDS: [");
      if (max_bpm_arr[0] != -1) {
        Serial.print(max_bpm_arr[0]);
        for (int i=1; i<30; i++) {
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
        for (int i=1; i<30; i++) {
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
        for (int i=1; i<30; i++) {
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
        for (int i=1; i<30; i++) {
          if (min_ibi_arr[i] == -1)
            break;
          Serial.print(",");
          Serial.print(min_ibi_arr[i]);
        }
      }
      Serial.println("]");
      Serial.println();
      Serial.println();

      Serial.print("Highest bpm value read (max_bpm_loop) = ");
      Serial.println(max_bpm_loop);
      Serial.print("Lowest bpm value read (min_bpm_loop) = ");
      Serial.println(min_bpm_loop);
      Serial.print("Highest ibi value read (max_ibi_loop) = ");
      Serial.println(max_ibi_loop);
      Serial.print("Lowest ibi value read (min_ibi_loop) = ");
      Serial.println(min_ibi_loop);
      Serial.println();
      Serial.println("End of story. Bye bye.");
      while (1);
    }
    
    Serial.println("Reading temperature in 5 seconds...");
    seconds = rtc.getSeconds();
    
    if (seconds > 54)
      seconds = 5 - (60 - seconds);
    else
      seconds += 5;
    rtc.setAlarmSeconds(seconds);
    rtc.enableAlarm(rtc.MATCH_SS);
    rtc.attachInterrupt(get_temperature);
  }
}
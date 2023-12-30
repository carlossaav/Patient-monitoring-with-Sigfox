#define USE_ARDUINO_INTERRUPTS false
#include <PulseSensorPlayground.h>
#include <SigFox.h>
#include <RTCZero.h>
#include <Wire.h>
#include <Protocentral_MAX30205.h>
#include <TimerObject.h>

#define PULSE_PIN 0            // PulseSensor WIRE connected to ANALOG PIN 0
#define NOISE_PIN 4            // Provide a random input with analogRead() on this pin for the random number generator
#define INPUT_BUTTON_PIN 5     // DIGITAL PIN 5 USED TO INTERRUPT whenever the button is pressed
#define SIGFOX_LED LED_BUILTIN
#define SENSORS_LED 7          // Blinks with every heartbeat
#define EMERGENCY_LED 8        // Used on emergencies

#define PULSE_THRESHOLD 2150   // Determine which Signal to "count as a beat" and which to ignore

#define UPPER_BPM_MEASURE 0
#define UPPER_BPM_LIMIT 110
#define LOWER_BPM_MEASURE 1
#define LOWER_BPM_LIMIT 65

#define UPPER_TEMP_MEASURE 2
#define UPPER_TEMP_LIMIT 37.5
#define LOWER_TEMP_MEASURE 3
#define LOWER_TEMP_LIMIT 35.5


/*
#define UPPER_IBI_MEASURE 3
#define UPPER_IBI_LIMIT 3000
#define UPPER_IBI_ELIMIT 3500
#define LOWER_IBI_MEASURE 4
#define LOWER_IBI_LIMIT 500
#define LOWER_IBI_ELIMIT 250
*/

#define RECEIVING_BUFFER_SIZE 8
#define SHIPMENT_BUFFER_SIZE 12

/* Message types. Critical order** */
#define ALARM_MSG 0
#define LIMITS_MSG 1
#define ALARM_LIMITS_MSG 2
#define ERROR_MSG 3
#define REC_ALARM_MSG 4
#define REC_LIMITS_MSG 5
#define REC_ALARM_LIMITS_MSG 6
#define REPORT_MSG 7

// Time before enabling 'critical' emergency shipment's rate again
#define NEW_EMERG_DELAY 1200000 // 20 min

#define BPM_LIM_EPOL_TRIGGERING 30000 // 30 seconds
#define BOTH_LIMITS_EXCEEDED_DELAY 900000 // 15 minutes

#define MAX_UPLINK_MSGS 140
#define SHIPMENT_INTERVAL 630000  // 10'30"
#define SHIPMENT_INTERVAL_MIN ((float)(SHIPMENT_INTERVAL/1000)/60.0)
// if SHIPMENT_INTERVAL == 10'30", at 23:58:30, msg == 137

#define MIN_SAMPLING_INTERVAL 30000 // Must be non-negative
#define REMAINING_MSG  MAX_UPLINK_MSGS - (int)(1440.0/SHIPMENT_INTERVAL_MIN)
#define SHIPMENT_RETRY 45000      // Time to retry a failed shipment
#define MAX_SHIPMENT_RETRIES 5

// In case of Sigfox or PulseSensor chipset failure
#define CHECK_ERROR_COND 30000
#define FAILED_DOWNLINK_RECEPTION 62 // ("0x62")

/* Every call to getBeatsPerMinute() and getInterBeatIntervalMs()
 * on loop() function takes place every 2 milliseconds --> Sample rate of 2 ms */
#define LOOP_DELAY 2

// Default values on Temperature or PulseSensor errors
#define BPM_READING_ERR 0  // Must be positive number or zero
#define TEMP_READING_ERR -1.0

#define TEMP_MEASURING_DELAY 1200000 // Minimal delay on milliseconds to send temperature again (20 min)

#define EMERG_FLASH 2000  // keep the EMERGENCY_LED 2 seconds flashing on emergency
#define BUG_FLASH 4000    // keep the SIGFOX_LED||SENSORS_LED 4 seconds flashing on error

#define CRITIC_ESEQ_REF 1
#define NON_CRITIC_ESEQ_REF 2

#define MAX_RECOVERY_MSG 30 // IMPORTANT, DO NOT SET THIS VALUE HIGHER THAN 255.
#define MAX_RECOVERY_TIME 21600000 // 6 hours

/** Variables **/

// Measurements
byte max_bpm, min_bpm, avg_bpm;
unsigned int max_ibi, min_ibi, avg_ibi;
unsigned int sum_bpm, sum_ibi;

byte range_top; // Determined by ranges width
byte ubpm_lim = UPPER_BPM_LIMIT;
byte lbpm_lim = LOWER_BPM_LIMIT;

float utemp_lim = UPPER_TEMP_LIMIT;
float ltemp_lim = LOWER_TEMP_LIMIT;

/* To later process where bpm readings have been falling across the interval, 
 * we'll define a set of BPM Ranges:
 * ranges[0] stores bpm reading counts in range [0, lbpm_lim-1]
 * ranges[1] stores bpm reading counts in range [lbpm_lim, range_top]
 * ranges[2] stores bpm reading counts in range [range_top+1, ubpm_lim]
 * ranges[3] stores bpm reading counts in range [ubpm_lim+1, infinite]
 */
int ranges[4] = {0,0,0,0};

// Buffers for sending and receiving
byte recv_buff[RECEIVING_BUFFER_SIZE];
byte send_buff[SHIPMENT_BUFFER_SIZE];

/* In case the failed shipment is from
 * the payload that triggered the emergency,
 * we'll save that payload */
byte rec_matrix_index = 0;
byte rec_matrix_counter = 0;
byte rec_matrix[MAX_RECOVERY_MSG][SHIPMENT_BUFFER_SIZE];

struct bpm_limit {
  unsigned int counter;  // Counter of times the measure (high or low bpm limit) has been exceeded
  unsigned long tstamp;  // last limit exceeded timestamp
};

/* bpm_limits[0][1] for upper and lower bpm measurements */
struct bpm_limit bpm_limits[2];

byte ubpm_lim_cond_set = 0;
byte lbpm_lim_cond_set = 0;
unsigned long ubpm_lim_cond_timestamp = 0;
unsigned long lbpm_lim_cond_timestamp = 0;

/* Time threshold allowed exceeding a bpm limit without activating 
 * Emergency shipment's policy. */
unsigned long bpm_lim_epol_trigg = BPM_LIM_EPOL_TRIGGERING;

// Time to reach the opposite bpm limit again
unsigned long both_exceeded_delay = BOTH_LIMITS_EXCEEDED_DELAY;


/* Counters */
int msg = 0; // sent messages
unsigned int bpm_ibi_sample_counter = 0;
unsigned long limits_exceeded_counter = 0;

byte ship_attempt = 0;      // Shipment attempts
unsigned long shipment = 0; // Last shipment timestamp
unsigned long amsg = 0;     // Last ALARM_MSG timestamp

/* Last timestamp of a shipment caused by
 * an emergency limit exceeded detection */
unsigned long elim_msg = 0;

byte elim = 0; // elim exceeded detection

/* Shipment policies activation/deactivation timestamp.
 * (epol_act is also the timestamp of an emergency activation condition) */
unsigned long epol_act = 0, epol_deact = 0;
unsigned long rpol_act = 0; // Recovery shipment policy activation timestamp

/* Shipment policies (activated/deactivated) */
byte epol = 0;
byte rpol = 0;

/* To differentiate between 'new emergencies'. If it is a new emergency,
 * the emergency shipment's policy will deliver reports faster than if
 * it's "actually the same emergency". The constant NEW_EMERG_DELAY 
 * differentiates between both situations. */
byte new_emergency = 1;
byte emergency = 0;

byte ereason_payload = 0; // Payload originating the current emergency

/* Emergency && Recovery shipment sequences */

int critic_eseq [] = {30000,60000,120000,300000,150000,420000,300000,420000};  // {30", 1', 2', 5', 2'30", 7', 5', 7'}
byte critic_eseq_length = (byte)(sizeof(critic_eseq) / sizeof(critic_eseq[0]));

int non_critic_eseq [] = {90000,210000,540000,360000};  // {1'30", 3'30", 9', 6'}
byte non_critic_eseq_length = (byte)(sizeof(non_critic_eseq) / sizeof(non_critic_eseq[0]));

int rec_critic_eseq [8];
byte rec_critic_eseq_length = critic_eseq_length;

int rec_non_critic_eseq [4];
byte rec_non_critic_eseq_length = non_critic_eseq_length;

// Go through the previous sequences
byte critic_eseq_index = 0;
byte rec_critic_eseq_index = 0;
byte non_critic_eseq_index = 0;
byte rec_non_critic_eseq_index = 0;

/* Before getting into any of the emergency sequences, we must
 * check whether it's going to be possible to recover the
 * delay generated by those sequences */
int potential_delay = 0;

// Alarm button purposes
volatile byte button_flag = 0;
byte button_pushed = 0;

// Led states
byte eled = LOW;
byte sigfox_led = LOW;
byte sensor_led = LOW;

// Indicate whether EMERGENCY_LED|SIGFOX_LED are flashing or not
byte eflash = 0;
byte sigfox_flash = 0;

// Indicate error on sigfox|sensors
byte sigfox_err = 0;
byte pulsesensor_err = 0;
byte temp_err = 0;

byte downlink_done = 0;

PulseSensorPlayground pulseSensor;
RTCZero rtc;
MAX30205 tempSensor;

TimerObject *ship_timer = new TimerObject(SHIPMENT_INTERVAL, &send_measurements);
TimerObject *sigfox_check_timer = new TimerObject(CHECK_ERROR_COND, &sigfox_check);
TimerObject *sensor_check_timer = new TimerObject(CHECK_ERROR_COND, &pulsesensor_check);

TimerObject *sigfox_led_timer = new TimerObject((unsigned long int)BUG_FLASH, &flash_sigfox_led);
TimerObject *sensors_led_timer = new TimerObject((unsigned long int)BUG_FLASH, &flash_sensors_led);
TimerObject *eled_timer = new TimerObject((unsigned long int)EMERG_FLASH, &flash_emergency_led);


void setup() {

  Wire.begin();
  analogReadResolution(12);
  randomSeed(analogRead(NOISE_PIN));

  pinMode(INPUT_BUTTON_PIN, INPUT_PULLUP); // button press
  pinMode(SIGFOX_LED, OUTPUT);
  pinMode(SENSORS_LED, OUTPUT);
  pinMode(EMERGENCY_LED, OUTPUT);

  digitalWrite(SIGFOX_LED, LOW);
  digitalWrite(SENSORS_LED, LOW);
  digitalWrite(EMERGENCY_LED, LOW);

  attachInterrupt(digitalPinToInterrupt(INPUT_BUTTON_PIN), button_pressed, FALLING);

  set_range_top();
  set_rec_seqs();
  reset_measures();
  reset_buff(recv_buff);
  reset_buff(send_buff);

  for (int i=0; i<(sizeof(bpm_limits) / sizeof(bpm_limits[0])); i++)
    bpm_limits[i].tstamp = 0;

  for (int i=0; i<MAX_RECOVERY_MSG; i++)
    reset_buff(rec_matrix[i]);

  disable_timer(eled_timer);

  /* Checking  Sigfox Module... */

  /* SigFox.noDebug() call triggers failures on sketch uploads due to
   * power saving features. Leave it commented */
  // SigFox.noDebug();  

  /* Indicate signal event, disable power saving features 
   * by default to gain time accuracy on shipments.*/
  SigFox.debug();
  sigfox_check();
  if (!sigfox_err) {
    disable_timer(sigfox_check_timer);
    disable_timer(sigfox_led_timer);
    SigFox.end(); // Send the module to sleep
  }

  // Configure the PulseSensor object
  pulseSensor.analogInput(PULSE_PIN);
  pulseSensor.setThreshold(PULSE_THRESHOLD);
  pulseSensor.blinkOnPulse(SENSORS_LED);  // blink SENSORS_LED with every heartbeat

  /* Checking sensors... */

  disable_timer(sensor_check_timer);
  disable_timer(sensors_led_timer);

  if (!pulseSensor.begin()) {
    pulsesensor_err = 1;
    pulsesensor_check();  // Initiate regular PulseSensor checking on error
  }

  if (!tempSensor.scanAvailableSensors())
    temp_err = 1;

  if (pulsesensor_err || temp_err)
    flash_sensors_led();

  rtc.begin();
  rtc.setTime(0, 0, 1); // Initially assume it's 00:00:01 h

  rtc.setAlarmTime(0, 0, 0); // Set alarm at 00:00:00 h
  rtc.enableAlarm(rtc.MATCH_HHMMSS);
  rtc.attachInterrupt(reset_day);

  sched_shipment(SHIPMENT_INTERVAL);
}


void set_range_top() {
  byte aux = (byte)floor((ubpm_lim - lbpm_lim)/2);
  range_top = lbpm_lim + aux;
  if (((ubpm_lim - lbpm_lim) % 2) == 0) // even number
    range_top--;
}


/* Executed at 00:00:00 h */
void reset_day() {
  msg = 0;
  set_rec_seqs();
}

void set_rec_seqs() {

  for (int i=0; i<rec_critic_eseq_length; i++)
    rec_critic_eseq[i] = (int)SHIPMENT_INTERVAL + ((int)SHIPMENT_INTERVAL - critic_eseq[i]);

  for (int i=0; i<rec_non_critic_eseq_length; i++)
    rec_non_critic_eseq[i] = (int)SHIPMENT_INTERVAL + ((int)SHIPMENT_INTERVAL - non_critic_eseq[i]);

  /* Rearrange rec_critic_eseq */
  for (int z, j, i=0; i<rec_critic_eseq_length; i++) {
    while ((j = random(rec_critic_eseq_length))==i);
    z = rec_critic_eseq[j];
    rec_critic_eseq[j] = rec_critic_eseq[i];
    rec_critic_eseq[i] = z;
  }

  /* Rearrange rec_non_critic_eseq */
  for (int z, j, i=0; i<rec_non_critic_eseq_length; i++) {
    while ((j = random(rec_non_critic_eseq_length))==i);
    z = rec_non_critic_eseq[j];
    rec_non_critic_eseq[j] = rec_non_critic_eseq[i];
    rec_non_critic_eseq[i] = z;
  }
}

void reset_buff(byte arr[]) {
  for (int i=0; i<(sizeof(arr)); i++)
    arr[i] = 0;
}


// Flash SIGFOX_LED on sigfox module error
void flash_sigfox_led() {

  sigfox_led_timer->Stop();

  if (sigfox_err) {
    sigfox_led = !sigfox_led;
    digitalWrite(SIGFOX_LED, sigfox_led);
    sched_event(sigfox_led_timer, BUG_FLASH);
  }
  else {
    sigfox_led = LOW;
    digitalWrite(SIGFOX_LED, LOW);
    disable_timer(sigfox_led_timer);
    sigfox_flash = 0;
  }
}

// Flash SENSORS_LED on sensor error
void flash_sensors_led() {

  sensors_led_timer->Stop();

  if (pulsesensor_err || temp_err) {
    sensor_led = !sensor_led;
    digitalWrite(SENSORS_LED, sensor_led);
    sched_event(sensors_led_timer, BUG_FLASH);
  }
  else {
    sensor_led = LOW;
    digitalWrite(SENSORS_LED, LOW);
    disable_timer(sensors_led_timer);
  }
}


// Flash EMERGENCY_LED on emergency
void flash_emergency_led() {

  eled_timer->Stop();

  if (emergency_active()) {
    eled = !eled;
    digitalWrite(EMERGENCY_LED, eled);
    sched_event(eled_timer, EMERG_FLASH);
  }
  else {
    eled = LOW;
    digitalWrite(EMERGENCY_LED, LOW);
    disable_timer(eled_timer);
    eflash = 0;
  }
}


void pulsesensor_check() {

  byte round = 0;

  sensor_check_timer->Stop();

  while (!pulseSensor.begin()) {
    if (++round==5) { // Ensure at least 5 calls
      sched_event(sensor_check_timer, CHECK_ERROR_COND);
      return;
    }
  }
  pulsesensor_err = 0;
  disable_timer(sensor_check_timer);
}


void sigfox_check() {

  byte round = 0;

  sigfox_check_timer->Stop();

  if (!sigfox_err) {
    if (init_sigfox_module()==0) {
      disable_timer(sigfox_check_timer);
      return;
    }
  }

  sigfox_err = 1; // Sigfox shield error
  if (!sigfox_flash) {
    sigfox_flash = 1;
    flash_sigfox_led();
  }

  while (!SigFox.begin()) {
    SigFox.status(); // Clears all pending interrupts
    SigFox.reset();
    if (++round==5) { // Ensure at least 5 calls
      sched_event(sigfox_check_timer, CHECK_ERROR_COND);
      return;
    }
  }
  sigfox_err = 0;
  disable_timer(sigfox_check_timer);
}


int init_sigfox_module() {
  if (SigFox.begin()) {
    sigfox_err = 0;
    SigFox.status();
    return 0;
  }
  return 1;
}


void reset_measures() {

  /* Initialize these vars to unlikely (impossible) values */

  max_bpm = 0;
  min_bpm = 255;
  avg_bpm = 0;
  sum_bpm = 0;

  max_ibi = 0;
  min_ibi = 10000;
  avg_ibi = 0;
  sum_ibi = 0;

  for (int i=0; i<(sizeof(ranges) / sizeof(ranges[0])); i++)
    ranges[i] = 0;

  for (int i=0; i<(sizeof(bpm_limits) / sizeof(bpm_limits[0])); i++)
    bpm_limits[i].counter = 0;

  bpm_ibi_sample_counter = 0;
  limits_exceeded_counter = 0;
}


// Returns whether there's any delay on shipment's logic
byte calc_delay() {

  int expected_msg;
  float min_day;

  min_day =  (float)(rtc.getHours()*60) + (float)rtc.getMinutes() + (((float)rtc.getSeconds())/60.0);
  expected_msg = ((int)(min_day/SHIPMENT_INTERVAL_MIN)) + REMAINING_MSG;

  if (msg <= expected_msg) return 0;
  return 1;
}


//Developing
int predict_delay(byte eseq) {

  int code = 0;
  byte delay = calc_delay(); // Check whether there's any accumulated delay already

  if (eseq == CRITIC_ESEQ_REF) {
    /* if (succesful prediction) code = 0;
     * else code = 1; */
  }
  else { // eseq == NON_CRITIC_ESEQ_REF
    /* if (succesful prediction) code = 0;
     * else code = 2; */
  }
  return code;
}


unsigned long check_interval(int interval) {
  if (interval < (int)MIN_SAMPLING_INTERVAL)
    return (unsigned long)MIN_SAMPLING_INTERVAL;
  return (unsigned long)interval;
}


void resched_ship_pol(unsigned long delay) {

  byte *index;
  byte seq_length;
  int *seq;
  byte acc_delay = calc_delay(); // Check whether there's any accumulated delay already

 // Initially schedule next shipment in (SHIPMENT_INTERVAL - delay) milliseconds
  sched_shipment(check_interval((int)SHIPMENT_INTERVAL - (int)delay));

  if (epol_active()) {

    if (new_emergency) {
      seq = critic_eseq;
      index = &critic_eseq_index;
      seq_length = critic_eseq_length;
    }
    else {
      seq = non_critic_eseq;
      index = &non_critic_eseq_index;
      seq_length = non_critic_eseq_length;
    }

    if (msg == MAX_UPLINK_MSGS) {
      deact_emergency();
      deact_epol();
      if (acc_delay > 0) act_rpol();
    }
    else {
      if (*index == seq_length) {
        deact_emergency();
        deact_epol();
        if (acc_delay > 0) act_rpol();
      }
      else {
        sched_shipment(check_interval(seq[*index] - (int)delay));
        (*index)++;
      }
    }
  }
  else if (!rpol_active() && (acc_delay > 0)) act_rpol();

  if (rpol_active()) {
    if (acc_delay==0) deact_rpol();
    else {
      if (new_emergency) {
        seq = rec_critic_eseq;
        index = &rec_critic_eseq_index;
        seq_length = rec_critic_eseq_length;
      }
      else {
        seq = rec_non_critic_eseq;
        index = &rec_non_critic_eseq_index;
        seq_length = rec_non_critic_eseq_length;
      }
      sched_shipment(check_interval(seq[*index] - (int)delay));
      if (++(*index) == seq_length)
        *index = 0;
    }
  }
}


// Insert tstamp into last 4 bytes of rec_matrix[rec_matrix_index] buff
void write_rec_tstamp(unsigned long *tstamp) {

  byte *p = (byte *)tstamp;

  for (int i=(SHIPMENT_BUFFER_SIZE-4), j=(sizeof (*tstamp)-1); i<SHIPMENT_BUFFER_SIZE, j>=0; i++, j--)
    rec_matrix[rec_matrix_index][i] = p[j]; // Little endian arch
}


void write_dec_to_bin(byte *var, byte number, byte left_bit, byte nbits) {

  /* nbits must be equal to 2 or 3 bits.
   * Left bit is the most significant bit on *var.
   * Higher values are more significant */
  
  byte right_bit;

  if (nbits == 2)
    right_bit = left_bit - 1;
  else // nbits == 3
    right_bit = left_bit - 2;
    

  switch (number) {
    case 0:
      bitWrite(*var, right_bit, 0);
      bitWrite(*var, right_bit+1, 0);
      if (nbits==3) bitWrite(*var, right_bit+2, 0);
      break;
    case 1:
      bitWrite(*var, right_bit, 1);
      bitWrite(*var, right_bit+1, 0);
      if (nbits==3) bitWrite(*var, right_bit+2, 0);
      break;
    case 2:
      bitWrite(*var, right_bit, 0);
      bitWrite(*var, right_bit+1, 1);
      if (nbits==3) bitWrite(*var, right_bit+2, 0);
      break;
    case 3:
      bitWrite(*var, right_bit, 1);
      bitWrite(*var, right_bit+1, 1);
      if (nbits==3) bitWrite(*var, right_bit+2, 0);
      break;
    case 4: // nbits == 3
      bitWrite(*var, right_bit, 0);
      bitWrite(*var, right_bit+1, 0);
      bitWrite(*var, right_bit+2, 1);
      break;
    case 5: // nbits == 3
      bitWrite(*var, right_bit, 1);
      bitWrite(*var, right_bit+1, 0);
      bitWrite(*var, right_bit+2, 1);
      break;
    case 6: // nbits == 3
      bitWrite(*var, right_bit, 0);
      bitWrite(*var, right_bit+1, 1);
      bitWrite(*var, right_bit+2, 1);
      break;
    case 7: // nbits == 3
      bitWrite(*var, right_bit, 1);
      bitWrite(*var, right_bit+1, 1);
      bitWrite(*var, right_bit+2, 1);
      break;
  }
}


void handle_failed_shipment() {

  /* The reason why a shipment could fail is either
   * we've got to the maximum of messages in one day
   * or to the established top for shipment retries */

  if (bitRead(send_buff[0], 6)) {  // Read ereason bit from send_buff[]

    unsigned long tstamp;

    /* Saving Triggering emergency payload... */

    for (int i=0; i<(SHIPMENT_BUFFER_SIZE - 4); i++)
      rec_matrix[rec_matrix_index][i] = send_buff[i];

    // Next setting is possible given the current message type order
    bitSet(rec_matrix[rec_matrix_index][0], 3); // Set message type == REC_X_MSG.

    // Set payload format indicator bits to 7
    bitWrite(rec_matrix[rec_matrix_index][1], 5, 1);
    bitWrite(rec_matrix[rec_matrix_index][2], 2, 1);
    bitWrite(rec_matrix[rec_matrix_index][4], 7, 1);

    tstamp = millis();
    write_rec_tstamp(&tstamp);

    if (++rec_matrix_index == MAX_RECOVERY_MSG)
      rec_matrix_index = 0;
    if (rec_matrix_counter < MAX_RECOVERY_MSG)
      rec_matrix_counter++;
  }

  reset_measures();
  reset_buff(send_buff);
  resched_ship_pol(0);
  ship_attempt = 0;
  ereason_payload = 0;
}


void check_retry() {
  if (ship_attempt == MAX_SHIPMENT_RETRIES)
    handle_failed_shipment();
  else {
    ereason_payload = (byte)bitRead(send_buff[0], 6);
    reset_buff(send_buff);
    sched_shipment(SHIPMENT_RETRY);
  }
}


void get_downlink(unsigned long delay) {

  byte aux = 0, hour = 0, min = 0, sec = 0;
  unsigned int conv, quotient;
  float aux_temp = 35.0;
  int i=0;

  /* Get hour from recv_buff */
  for (int i=4; i>=0; i--)
    bitWrite(hour, i, bitRead(recv_buff[0], i+3));

  /* Get minutes from recv_buff */
  for (int i=5; i>=3; i--)
    bitWrite(min, i, bitRead(recv_buff[0], i-3));
  for (int i=2; i>=0; i--)
    bitWrite(min, i, bitRead(recv_buff[1], i+5));

  /* Get seconds from recv_buff */
  for (int i=5; i>=1; i--)
    bitWrite(sec, i, bitRead(recv_buff[1], i-1));
  bitWrite(sec, 0, bitRead(recv_buff[2], 7));

  conv = (unsigned int)sec + delay;
  quotient = (conv / 60);
  sec = (byte)(conv % 60);

  if (quotient != 0) {
    conv = (unsigned int)min + quotient;
    quotient = conv / 60;
    min = (byte)(conv % 60);
    hour += quotient;
    hour %= 24;
  }

  rtc.setTime(hour, min, sec);

  bpm_lim_epol_trigg = 0;
  aux = 0;
  for (int i=6; i>=0; i--)
    bitWrite(aux, i, bitRead(recv_buff[2], i));

  // Convert it to milliseconds
  bpm_lim_epol_trigg = (unsigned long)aux * 1000;

  msg = recv_buff[3];      // get amount of uplink messages sent on the day
  ubpm_lim = recv_buff[4]; // get upper bpm limit
  lbpm_lim = recv_buff[5]; // get lower bpm limit

  /* Extract max and min temperatures */

  utemp_lim = 0;
  aux = 0;
  for (int i=7; i>=6; i--)
    bitWrite(aux, i-6, bitRead(recv_buff[6], i));

  aux_temp += (float)aux; // Add the integer part
  aux = 0;
  for (int i=5; i>=2; i--)
    bitWrite(aux, i-2, bitRead(recv_buff[6], i));

  aux_temp += (float)aux/10; // Add the decimal part
  utemp_lim = aux_temp; // Set upper temperature limit

  // Repeat the process for ltemp_lim
  ltemp_lim = 0;
  aux_temp = 35.0;
  aux = 0;
  for (int i=1; i>=0; i--)
    bitWrite(aux, i, bitRead(recv_buff[6], i));

  aux_temp += (float)aux;
  aux = 0;
  for (int i=7; i>=4; i--)
    bitWrite(aux, i-4, bitRead(recv_buff[7], i));

  aux_temp += (float)aux/10;
  ltemp_lim = aux_temp; // Set lower temperature limit

  // Get both_exceeded_delay value in minutes from recv_buff
  aux = 0;
  for (int i=3; i>=0; i--)
    bitWrite(aux, i, bitRead(recv_buff[7], i));

  both_exceeded_delay = (unsigned long)aux * 60000; // Translate it to milliseconds
}


void send_measurements() {

  static float temp;
  static unsigned long tstamp, temp_tstamp = 0;
  byte msg_type = REPORT_MSG;
  byte buff_size, payload_format, code;

  if (ship_attempt++==0) {
    byte i=0;

    tstamp = millis();
    ship_timer->Stop();

    while (temp_err) {
      if (++i==2) {
        temp = TEMP_READING_ERR; // Set temp value to TEMP_READING_ERR to indicate failure
        break;
      }
      if (tempSensor.scanAvailableSensors())
        temp_err = 0; // Temperature sensor detected
    }

    if (!temp_err) {
      tempSensor.begin();
      temp = tempSensor.getTemperature();
      temp_tstamp = millis();
      tempSensor.shutdown();

      if (check_upper_limit(temp))
        limit_exceeded(UPPER_TEMP_MEASURE, 0);
      else
        if (check_lower_limit(temp))
          limit_exceeded(LOWER_TEMP_MEASURE, 0);
    }
  }

  /* Set message type */

  if (pulsesensor_err || temp_err)
    msg_type = ERROR_MSG;

  if (limits_exceeded_counter) { // msg_type == REPORT_MSG/ERROR_MSG
    if (msg_type==ERROR_MSG) {
      if (bpm_limits[0].counter || bpm_limits[1].counter)
        msg_type = LIMITS_MSG; // if any of bpm limits was exceeded, prioritize LIMITS_MSG
    }
    else msg_type = LIMITS_MSG;
  }

  if (button_pushed) {
    switch (msg_type) {
      case LIMITS_MSG:
        msg_type = ALARM_LIMITS_MSG;
        break;
      default: // msg_type == REPORT_MSG/ERROR_MSG
        msg_type =  ALARM_MSG; // ERROR_MSG lost, prioritize ALARM_MSG messages.
    }
  }

  /* Calculate payload format indicator (type of payload) */

  if (msg_type == LIMITS_MSG || msg_type == ALARM_LIMITS_MSG) {  // payload format variants == 0/1/2

    unsigned int bpm_limits_counter = bpm_limits[0].counter + bpm_limits[1].counter;

    if (bpm_limits_counter != 0) {
      if (bpm_limits_counter < limits_exceeded_counter) // bpm and temperature limits exceeded on the interval
        payload_format = 0;
      else // bpm_limits_counter == limits_exceeded_counter (only bpm measure has been exceeded)
        payload_format = 1;
    }
    else while ((payload_format = random(3))==1); // only temperature limit exceeded (variants == 0/2)
  }
  else {
    if (msg_type == REPORT_MSG || msg_type == ALARM_MSG) {
      if ((temp_tstamp != 0) && ((millis() - temp_tstamp) < TEMP_MEASURING_DELAY))
        while ((payload_format = random(1, 4))==2); // payload format variants == 1/3
      else 
        payload_format = random(4); // payload format variants == 0/1/2/3
    }
    else  { // msg_type == ERROR_MSG
      if (pulsesensor_err) payload_format = 4;
      else
        payload_format = random(5, 7); // payload format variants == 5/6
    }
  }

  /* Configuring payload... */

  /* Setting payload format indicator bits... */

  bitWrite(send_buff[1], 5, bitRead(payload_format, 2));
  bitWrite(send_buff[2], 2, bitRead(payload_format, 1));
  bitWrite(send_buff[4], 7, bitRead(payload_format, 0));

  /* Setting first 7 bits of the payload...*/
  
  bitWrite(send_buff[0], 7, emergency_active()); // emergency field
  bitWrite(send_buff[0], 6, ereason_payload);    // emergency reason payload field

  // Shipment policy field
  if (epol_active()) write_dec_to_bin(&(send_buff[0]), 1, 5, 2);
  else {
    if (rpol_active()) write_dec_to_bin(&(send_buff[0]), 2, 5, 2);
    else // Regular shipment rate
      write_dec_to_bin(&(send_buff[0]), 0, 5, 2);
  }

  switch (msg_type) {  // Message type field setting
    case ALARM_MSG:
      write_dec_to_bin(&(send_buff[0]), 0, 3, 3);
      break;
    case LIMITS_MSG:
      write_dec_to_bin(&(send_buff[0]), 1, 3, 3);
      break;
    case ALARM_LIMITS_MSG:
      write_dec_to_bin(&(send_buff[0]), 2, 3, 3);
      break;
    case ERROR_MSG:
      write_dec_to_bin(&(send_buff[0]), 3, 3, 3);
      break;
    case REPORT_MSG:
      write_dec_to_bin(&(send_buff[0]), 7, 3, 3);
      break;
  }

  /* Computing measurements... */

  /* pulsesensor_check() might be scheduled to run periodically.
   * Just reading 'pulsesensor_err' variable without checking the value of
   * 'bpm_ibi_sample_counter' may lead to division by 0 on 'avg_bpm' computing,
   * since that function may set 'pulsesensor_err' variable to 0 before any
   * sample has been gathered. */

  if (pulsesensor_err || bpm_ibi_sample_counter==0)
    avg_bpm = BPM_READING_ERR; // avoid computing bpm fields
  else {
    int max_value = -1;
    int max_range_ids[3] = {-1,-1,-1};
    byte numerator, match, match_count, counter = 0;

    avg_bpm = (byte)round((float)sum_bpm/(float)bpm_ibi_sample_counter);
    avg_ibi = round((float)sum_ibi/(float)bpm_ibi_sample_counter);

    /* We want to save the indexes of the three highest values of ranges[] 
     * on max_range_ids[] */

    match = 0; match_count = 0;
    while (counter != 3) {
      byte skipped = 0;

      for (int i=0; i<(sizeof(ranges) / sizeof(ranges[0])); i++) {
        if (counter != 0) {
          if (match==0) {
            for (int j=0; j<counter; j++) {
              if (i==max_range_ids[j]) {
                match = 1; match_count++;
                break;
              }
            }
          }
          if (!skipped && match) { // counter != 0
            if (counter==1) skipped = 1;
            else // counter==2
              if (match_count < 2) match = 0;
              else skipped = 1;
            continue;
          }
        }
        if (ranges[i] > max_value) {
          max_value = ranges[i];
          max_range_ids[counter] = i;
        }
      }
      match = 0; match_count = 0; skipped = 0;
      max_value = -1; counter++;
    }

    /* Set range identifier bits */

    bitWrite(send_buff[0], 0, (max_range_ids[0] >= 4));
    write_dec_to_bin(&(send_buff[1]), (byte)(max_range_ids[0] % 4), 7, 2); // First range id setting
    write_dec_to_bin(&(send_buff[2]), (byte)max_range_ids[1], 5, 3);       // Second range id setting
    write_dec_to_bin(&(send_buff[3]), (byte)max_range_ids[2], 2, 3);       // Third range id setting

    /* Calculate and set percentages */

    for (int i=0, j; i<(sizeof(max_range_ids) / sizeof(max_range_ids[0])); i++) {
      j = max_range_ids[i];
      // Reuse max_range_ids[] to save numerators
      max_range_ids[i] = round(((float)ranges[j]/(float)bpm_ibi_sample_counter)*100.0);
    }

    numerator = (byte)max_range_ids[0];
    for (int i=4; i>=0; i--)
      bitWrite(send_buff[1], i, bitRead(numerator, i+2));
    bitWrite(send_buff[2], 7, bitRead(numerator, 1));
    bitWrite(send_buff[2], 6, bitRead(numerator, 0));

    numerator = (byte)max_range_ids[1];
    bitWrite(send_buff[2], 1, bitRead(numerator, 6));
    bitWrite(send_buff[2], 0, bitRead(numerator, 5));
    for (int i=7; i>=3; i--)
      bitWrite(send_buff[3], i, bitRead(numerator, i-3));

    numerator = (byte)max_range_ids[2];
    for (int i=6; i>=0; i--)
      bitWrite(send_buff[4], i, bitRead(numerator, i));
  }

  /* First 5 bytes of send_buff [0-4] written at this point. Writing from send_buff[5] onwards */

  send_buff[5] = avg_bpm;

  // Write max_bpm and min_bpm on corresponding payloads
  if (payload_format==0 || payload_format==1 || payload_format==5) {
    send_buff[6] = max_bpm;
    send_buff[7] = min_bpm;
  }

  // Write temp on corresponding payloads
  if (payload_format==0 || payload_format==2 || payload_format==4) {
    byte init_pos, end_pos;
    byte *p = (byte *)&temp;

    if (payload_format==4) {  // Write temp on bytes [6-9]. 10 byte packet !!
      end_pos = SHIPMENT_BUFFER_SIZE - 3;
      init_pos = SHIPMENT_BUFFER_SIZE - 6;
    }
    else  {  // Write temp on bytes [8-11]
      end_pos = SHIPMENT_BUFFER_SIZE - 1;
      init_pos = SHIPMENT_BUFFER_SIZE - 4;
    }
    for (int i=init_pos, j=(sizeof(temp)-1); i<=end_pos, j>=0; i++, j--)
      send_buff[i] = p[j]; // Little endian arch
  }

  // Write max_ibi and min_ibi on corresponding payloads
  if (payload_format==1 || payload_format==3 || payload_format==5 || payload_format==6) {

    byte *p = (byte *)&max_ibi; // Write max_ibi on bytes [8-9]
    for (int i=(SHIPMENT_BUFFER_SIZE-4), j=(sizeof(max_ibi)-3); i<(SHIPMENT_BUFFER_SIZE-2), j>=0; i++, j--)
      send_buff[i] = p[j]; // Little endian arch

    p = (byte *)&min_ibi;  // Write min_ibi on bytes [10-11]
    for (int i=(SHIPMENT_BUFFER_SIZE-2), j=(sizeof(min_ibi)-3); i<SHIPMENT_BUFFER_SIZE, j>=0; i++, j--)
      send_buff[i] = p[j]; // Little endian arch
  }

  // Write avg_ibi on corresponding payloads
  if (payload_format==2 || payload_format==3 || payload_format==6) {
    byte *p = (byte *)&avg_ibi; // Write avg_ibi on bytes [6-7]
    for (int i=(SHIPMENT_BUFFER_SIZE-6), j=(sizeof(avg_ibi)-3); i<=(SHIPMENT_BUFFER_SIZE-5), j>=0; i++, j--)
      send_buff[i] = p[j]; // Little endian arch
  }

  /* Sigfox Module checking */

  if (init_sigfox_module() != 0) {
    if (!sigfox_err) {
      sigfox_check();  // Initiate regular sigfox module checking
      if (sigfox_err) {
        check_retry();  // Hopefully, it's a temporary failure on Sigfox module
        return;
      }
      /* Atfter first checking, sigfox module has been initialized successfully.
       * Continue with the shipment */
    }
    else {  /* Regular sigfox module checking already in progress. */
      check_retry();
      return;
    }
  }

  pulseSensor.pause();

  /* Shipping... */

  buff_size = SHIPMENT_BUFFER_SIZE;
  if (payload_format == 4)  // 10 byte-packet
    buff_size = 10;

  SigFox.beginPacket();
  SigFox.write(send_buff, buff_size);

  if (!downlink_done) code = SigFox.endPacket(true);  // Set Downlink Request by passing true to endPacket()
  else code = SigFox.endPacket();

  if (code==0 ||
      SigFox.statusCode(SIGFOX)==FAILED_DOWNLINK_RECEPTION) {

    /* From https://github.com/divetm/Getting-started-with-Sigfox/blob/master/Sensit_project/sdk/inc/sigfox/sigfox_api.h:
     * (0x62): Error occurs during the nvm storage used for ack transmission.

     * It seems to be related to failed downlinnk requests. Count it as success, as it 
     * effectively ships the uplink message despite of such error */

    shipment = millis(); msg++;
    button_pushed = 0;
    ereason_payload = 0;

    if (msg_type == ALARM_MSG || msg_type == ALARM_LIMITS_MSG) {
      amsg = shipment;
      if (emergency_active() && (!epol_active()))
        deact_emergency();
    }

    if (elim) {
      elim_msg = shipment;
      elim = 0;
      if (emergency_active() && (!epol_active()))
        deact_emergency();
    }
    
    reset_measures();
    reset_buff(send_buff);

    if (!downlink_done && (SigFox.parsePacket() == RECEIVING_BUFFER_SIZE)) {
      // Extract Downlink Message
      reset_buff(recv_buff);
      for (int i=0; i<RECEIVING_BUFFER_SIZE; i++) {
        if (SigFox.available())
          recv_buff[i] = SigFox.read();
      }
      get_downlink(0);
      set_range_top();
      downlink_done = 1;
    }

    /* Pick up the last pending payload from rec_matrix[] and send it */

    if ((rec_matrix_counter != 0) && (msg < MAX_UPLINK_MSGS)) {

      unsigned long tstamp, aux;
      byte *p = (byte *)&tstamp;

      if (--rec_matrix_index==-1)
        rec_matrix_index = MAX_RECOVERY_MSG - 1;

      // Reading tstamp from last 4 bytes of rec_matrix[rec_matrix_index] buff
      for (int i=(SHIPMENT_BUFFER_SIZE-1), j=0; i>=(SHIPMENT_BUFFER_SIZE-4), j<sizeof (tstamp); i--, j++)
        p[j] = rec_matrix[rec_matrix_index][i]; // Little endian arch

      aux = tstamp;
      tstamp = millis() - tstamp;

      if (tstamp <= MAX_RECOVERY_TIME) {
        write_rec_tstamp(&tstamp);

        SigFox.beginPacket();
        SigFox.write(rec_matrix[rec_matrix_index], SHIPMENT_BUFFER_SIZE);

        if (SigFox.endPacket()==0) {  // Send buffer to SIGFOX network
          shipment = millis(); msg++;
          reset_buff(rec_matrix[rec_matrix_index]);
          if (--rec_matrix_counter==0)
            rec_matrix_index = 0;
        }
        else { // Just progress. Retry on next scheduled shipment
          write_rec_tstamp(&aux);
          if (++rec_matrix_index==MAX_RECOVERY_MSG)
            rec_matrix_index = 0;
        }
      }
      else { // liberate rec_matrix. All buffers on rec_matrix are old records (> MAX_RECOVERY_TIME)
        for (int i=rec_matrix_counter; i>0; i--) {
          reset_buff(rec_matrix[rec_matrix_index]);
          if (--rec_matrix_index==-1)
            rec_matrix_index = MAX_RECOVERY_MSG - 1;
        }
        rec_matrix_counter = 0;
        rec_matrix_index = 0;
      }
    }

    resched_ship_pol(millis() - tstamp);
    ship_attempt = 0;
  }
  else check_retry();

  SigFox.end();
  pulseSensor.resume();
}


void disable_timer(TimerObject *timer) {
  timer->Stop();
  timer->setEnabled(false);
}

void sched_event(TimerObject *timer, unsigned long ms) {
  timer->Stop(); // Reset timer
  timer->setInterval(ms);
  timer->setEnabled(true);
  timer->Start();
}

void sched_shipment(unsigned long ms) {
  if (ms==0) {
    ship_timer->Stop();
    send_measurements();
  }
  else
    sched_event(ship_timer, ms);
}


byte emergency_active() {
  return emergency;
}

byte epol_active() {
  return epol;
}

byte rpol_active() {
  return rpol;
}

void act_emergency() {
  emergency = 1;
}

void deact_emergency() {
  emergency = 0;
}

void act_rpol() {
  rpol = 1;
  rpol_act = millis();
}

void deact_rpol() {
  rpol = 0;
  rec_critic_eseq_index = 0;
  rec_non_critic_eseq_index = 0;
}

void act_epol() {
  epol = 1;
  epol_act = millis();
}

void deact_epol() {
  epol = 0;
  epol_deact = millis();
  critic_eseq_index = 0;
  non_critic_eseq_index = 0;
}


/* Check whether there will be time enough
 * to recover the delay generated by eseq emergency sequence.
 * Returns the emergency sequence that can be accessed.
 * If it's not possible to access any, returns 0.
 */
byte check_eseq_act(byte eseq) {

  byte seq = 0;

  if ((eseq == CRITIC_ESEQ_REF) && (predict_delay(CRITIC_ESEQ_REF)==0))
    seq = CRITIC_ESEQ_REF;
  else
    if (predict_delay(NON_CRITIC_ESEQ_REF)==0)
      seq = NON_CRITIC_ESEQ_REF;

  return seq;
}


/* Returns 1 if epol has been activated,
 * otherwise returns 0. */
byte fire_epol(byte alarm) {

  byte fired = 0;
  byte eseq, new_e;

  /* Check if last Emergency shipment's policy took place recently.
   * If so, deal with this as a continuation of the same emergency.
   */
  new_e = !(epol_deact != 0 && ((millis() - epol_deact) < NEW_EMERG_DELAY));

  if (new_e) eseq = CRITIC_ESEQ_REF;
  else {
    unsigned long tstamp = amsg;
    eseq = NON_CRITIC_ESEQ_REF;
    if (elim) tstamp = elim_msg;
    if ((elim||alarm) && (tstamp < epol_act))
      eseq = CRITIC_ESEQ_REF;
  }

  switch (check_eseq_act(eseq)) {
    case CRITIC_ESEQ_REF:
      new_emergency = 1;
      fired = 1;
      break;
    case NON_CRITIC_ESEQ_REF:
      new_emergency = 0;
      fired = 1;
      break;
  }

  if (fired) act_epol();
  return fired;
}


void admin_shipping(byte alarm) {

  unsigned long tstamp;

  if (alarm==0) tstamp = elim_msg;
  else tstamp = amsg;

  if ((rpol_active()) || (epol_active())) {
    if (tstamp < epol_act) {
      // No ALARM_MSG or LIMITS_MSG by elim have been sent in the last emergency policy (which could be running)
      if (rpol_active()) {
        if (fire_epol(alarm)) {
          deact_rpol();
          ereason_payload = 1;
          sched_shipment(0);
        }
      }
      else { // epol is ongoing
        byte eseq = check_eseq_act(CRITIC_ESEQ_REF);
        if (eseq) {
          if (eseq == CRITIC_ESEQ_REF) {
            critic_eseq_index = 0;
            new_emergency = 1;
          }
          else {
            if (critic_eseq_index > ((sizeof(critic_eseq) / sizeof(critic_eseq[0])) / 2)) {
              // It's worth giving up critic_eseq
              critic_eseq_index = 0;
              new_emergency = 0;
            }
          }
          non_critic_eseq_index = 0;
          sched_shipment(0);
        }
        /* If it's not possible to restart any of the eseqs,
         * just wait for the next scheduled shipment
         * on the ongoing eseq to notify it */
      }
    }
  }
  else // No policies active
    if (fire_epol(alarm)) {
      ereason_payload = 1;
      sched_shipment(0);
    }
}

void handle_button_pushed() {

  act_emergency();

  if (!eflash) {
    eflash = 1;
    flash_emergency_led();
  }

  admin_shipping(1);
}


/* Interrupt Service Routine button_pressed(),
 * triggered whenever the user pushes the emergency button */
void button_pressed() {
  button_flag = 1;
}


/* Functions to check if any 
 * elimit has been exceeded */
byte check_upper_elimit(byte bpm) {
  return (bpm > (ubpm_lim + 15));
}

byte check_lower_elimit(byte bpm) {
  return (bpm < (lbpm_lim - 10));
}


byte check_elimits(byte measure, byte value) {
  switch (measure) {
    case UPPER_BPM_MEASURE:
      return check_upper_elimit(value);
    case LOWER_BPM_MEASURE:
      return check_lower_elimit(value);
    default:
      return 0;
  }
}


void limit_exceeded(byte measure, byte value) {

  unsigned long tstamp = millis();
  unsigned long *bpm_lim_cond_timestamp;
  byte i;
  byte *bpm_lim_cond_set;
  static unsigned long idle_time; // shared between upper and lower bpm limits for 'bt' condition

  limits_exceeded_counter++;
  switch (measure) {
    case UPPER_BPM_MEASURE:
      i=0;
      bpm_lim_cond_set = (byte *)&ubpm_lim_cond_set;
      bpm_lim_cond_timestamp = (unsigned long *)&ubpm_lim_cond_timestamp;
      break;
    case LOWER_BPM_MEASURE:
      i=1;
      bpm_lim_cond_set = (byte *)&lbpm_lim_cond_set;
      bpm_lim_cond_timestamp = (unsigned long *)&lbpm_lim_cond_timestamp;
      break;
    default: // UPPER_TEMP_MEASURE || LOWER_TEMP_MEASURE
      return; // Do not continue, just count the temperature limit exceeded
  }

  bpm_limits[i].counter++;

  if (!epol_active() && !rpol_active()) {
    if (*bpm_lim_cond_set == 0) {
      /* Reset the monitoring of 'bt' condition */
      *bpm_lim_cond_set = 1;
      *bpm_lim_cond_timestamp = tstamp;
      idle_time = 0;
    }
    else {
      // Check out when last bpm limit exceeded took place 
      unsigned long aux = tstamp - bpm_limits[i].tstamp;
      if (aux > LOOP_DELAY) {
        /* Continuity broken between calls to limit_exceeded().
        * Such difference is not reflecting the real time exceeding a 
        * bpm limit. Something happened in betweeen calls to limit_exceeded(),
        * like a shipment, which may take more than 10 seconds to complete.
        * Store that '"idle time' to be substracted later on 'bt' condition checking. */

        // substract loop iteration time
        idle_time += (aux - LOOP_DELAY);
      }
    }
  }

  bpm_limits[i].tstamp = tstamp;

  if (check_elimits(measure, value)) {

    if (elim)
    /* Whatever elim has been exceeded, there's been
      * a previous elim before this one took place
      * that hasn't been attended yet. */
      return;

    elim = 1;
    act_emergency();
    admin_shipping(0);
  }

  if (epol_active() || rpol_active()) {
    *bpm_lim_cond_set = 0;
    return;
  }

  /* No policies active at this point.
   * Start by checking out 'bx' condition presence
   * (value shipped on downlink payload) */

  if (measure==UPPER_BPM_MEASURE) i++;
  else i--; // LOWER_BPM_MEASURE

  if ((bpm_limits[i].tstamp != 0) &&
     ((tstamp - bpm_limits[i].tstamp) <= both_exceeded_delay) &&
     fire_epol(0))
  {
    /* max and min limits of bpm violated within 'both_exceeded_delay' 
     * period ('bx' value). Activate Emergency shipment's policy. */
    act_emergency();
    ereason_payload = 1;
    sched_shipment(0);
    *bpm_lim_cond_set = 0; // Give up 'bpm_lim_epol_trigg' checking
    return;
  }

   /* If 'bx' 'didn't trigger epol, then check out for 'bt' condition,
    * (again, from downlink payload) */

  if ((((tstamp - *bpm_lim_cond_timestamp) - idle_time) >= bpm_lim_epol_trigg) &&
      fire_epol(0))
  {
    /* Emergency condition kept over 'bpm_lim_epol_trigg' milliseconds.
    * Activate Emergency shipment's policy. */
    act_emergency();
    ereason_payload = 1;
    sched_shipment(0);
    *bpm_lim_cond_set = 0; // Reset 'bpm_lim_epol_trigg' checking
  }
}


/* Overloaded function series to check
 * if any limit has been exceeded
 */
byte check_upper_limit(float temperature) {
  return (temperature > utemp_lim);
}

byte check_lower_limit(float temperature) {
  return (temperature < ltemp_lim);
}

byte check_upper_limit(byte bpm) {
  return (bpm > ubpm_lim);
}

byte check_lower_limit(byte bpm) {
  return (bpm < lbpm_lim);
}

void set_max_and_min(byte bpm, int ibi) {
  if (bpm > max_bpm)
    max_bpm = bpm;
  else
    if (bpm < min_bpm)
      min_bpm = bpm;

  if (ibi > max_ibi)
    max_ibi = ibi;
  else
    if (ibi < min_ibi)
      min_ibi = ibi;
}


byte bytecast(int value) {
  if (value<0)
    return (byte)0;
  else
    if (value>255)
      return (byte)255;
  return byte(value);
}

void loop() {

  byte bpm;
  int ibi;

  if (eled_timer->isEnabled())
    eled_timer->Update();

  if (button_flag) {
    if (!button_pushed) {
      button_pushed = 1;
      handle_button_pushed();
    }
    button_flag = 0;
  }

  /* See if a sample is ready from the PulseSensor.
     If USE_INTERRUPTS is false, this call to sawNewSample()
     will, if enough time has passed, read and process a
     sample (analog voltage) from the PulseSensor. */

  if (!pulsesensor_err && pulseSensor.sawNewSample()) {
    bpm = bytecast(pulseSensor.getBeatsPerMinute());
    ibi = pulseSensor.getInterBeatIntervalMs();
    sum_bpm += bpm;
    sum_ibi += ibi;
    bpm_ibi_sample_counter++; // count bpm and ibi readings
    set_max_and_min(bpm, ibi);

    if (bpm<lbpm_lim) ranges[0]++;
    else if (bpm>=lbpm_lim && bpm<=range_top) ranges[1]++;
    else if (bpm>=(range_top+1) && bpm<=ubpm_lim) ranges[2]++;
    else ranges[3]++; // bpm > ubpm_lim

    // check limits
    if (check_upper_limit(bpm)) {
      lbpm_lim_cond_set = 0;
      limit_exceeded(UPPER_BPM_MEASURE, bpm);
    }
    else {
      ubpm_lim_cond_set = 0;
      if (check_lower_limit(bpm))
        limit_exceeded(LOWER_BPM_MEASURE, bpm);
      else
        lbpm_lim_cond_set = 0;
    }
  }

  if (sigfox_led_timer->isEnabled())
    sigfox_led_timer->Update();
  if (sigfox_check_timer->isEnabled())
    sigfox_check_timer->Update();
  if (sensors_led_timer->isEnabled())
    sensors_led_timer->Update();
  if (sensor_check_timer->isEnabled())
    sensor_check_timer->Update();
  
  ship_timer->Update();
}

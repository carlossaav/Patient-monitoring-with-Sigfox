#define USE_ARDUINO_INTERRUPTS false
#include <PulseSensorPlayground.h>
#include <SigFox.h>
#include <RTCZero.h>
#include <Wire.h>
#include <Protocentral_MAX30205.h>


#define PULSE_PIN 0            // PulseSensor WIRE connected to ANALOG PIN 0
#define INPUT_BUTTON_PIN 5     // DIGITAL PIN 5 USED TO INTERRUPT whenever the button is pressed
#define SENSORS_LED 7          // Blinks with every heartbeat
#define EMERGENCY_LED 8        // Used on emergencies
#define SIGFOX_LED LED_BUILTIN

#define PULSE_THRESHOLD 2140   // Determine which Signal to "count as a beat" and which to ignore

#define UPPER_BPM_MEASURE 0
#define UPPER_BPM_LIMIT 125
#define UPPER_BPM_ELIMIT 150
#define LOWER_BPM_MEASURE 1
#define LOWER_BPM_LIMIT 60
#define LOWER_BPM_ELIMIT 50

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


/* 32 KB SRAM
#define MAX_BPM_SAMPLES 600
#define MAX_IBI_SAMPLES 600
*/

#define RECEIVING_BUFFER_SIZE 8
#define SHIPMENT_BUFFER_SIZE 12

#define REPORT_MSG 0
#define LIMITS_MSG 1
#define ALARM_MSG 2 
#define ALARM_LIMITS_MSG 3
#define ERROR_MSG 4

/* To later process where bpm readings have been falling across the interval, 
 * we'll define a set of BPM Ranges */
#define LOWER_THAN_FIFTY 000
#define FIFTY_TO_SEVENTY 001
#define SEVENTY_TO_NINETY 010
#define NINETY_TO_HUNDRED_TEN 011
#define HUNDRED_TEN_TO_HUNDRED_THIRTY 100
#define HUNDRED_THIRTY_TO_HUNDRED_FIFTY 101
#define HUNDRED_FIFTY_TO_HUNDRED_SEVENTY 110
#define HIGHER_THAN_HUNDRED_SEVENTY 111

// Time before enabling 'critical' emergency shipment's rate again
#define NEW_EMERG_DELAY 1200000 // 20 min

// Limits exceeded counter threshold to activate Emergency shipment's policy
#define LIM_COUNT_EPOL_TRIGGERING 10


#define MAX_UPLINK_MSGS 140
// #define MAX_DOWNLINK_MSGS ?
#define SHIPMENT_INTERVAL 630000  // 10'30"
#define SHIPMENT_INTERVAL_MIN ((float)(SHIPMENT_INTERVAL/1000)/60.0)
// if SHIPMENT_INTERVAL == 10'30", at 23:58:30, msg == 137

#define MIN_SAMPLING_INTERVAL 30000 // Must be non-negative
#define REMAINING_MSG  MAX_UPLINK_MSGS - (int)(1440.0/SHIPMENT_INTERVAL_MIN)
#define SHIPMENT_RETRY 12000      // Time to retry a failed shipment
#define MAX_SHIPMENT_RETRIES 5

// In case of Sigfox or PulseSensor chipset failure
#define CHECK_ERROR_COND 30000


// Default values on Temperature or PulseSensor errors
#define BPM_READING_ERR -1
#define TEMP_READING_ERR -1.0


// keep the EMERGENCY_LED 2 seconds flashing on emergency
#define EMERG_FLASH 2000
// keep the SIGFOX_LED||SENSORS_LED 4 seconds flashing on error
#define BUG_FLASH 4000


#define SHIPMENT_TIMER 0


#define CRITIC_ESEQ_REF 1
#define NON_CRITIC_ESEQ_REF 2

/*
#define CRITIC_ESEQ_DURATION 30.0
#define NON_CRITIC_ESEQ_DURATION 
#define REC_CRITIC_ESEQ_DURATION 
#define REC_NON_CRITIC_ESEQ_DURATION
*/

/** Variables **/

struct msg_format {
};

// Measurements
byte max_bpm, min_bpm;
int max_ibi, min_ibi;
float avg_bpm, avg_ibi, sd_bpm, sd_ibi;
// variances/ranges?

/*
// Sampling buffers
byte bpm_hist[MAX_BPM_SAMPLES];
int ibi_hist[MAX_IBI_SAMPLES]; // evaluate data type
*/

// Buffers for sending and receiving
byte recv_buff[RECEIVING_BUFFER_SIZE];
byte send_buff[SHIPMENT_BUFFER_SIZE];

/* In case the failed shipment is from
 * the payload that triggered the emergency,
 * we'll save that payload */
byte rec_buff[SHIPMENT_BUFFER_SIZE];

/*
  For upper and lower bpm limits, limits_exceeded stores how many
  times those limits have been exceeded.
  - limits_exceeded[0][1] for upper and lower bpm limit counts
*/
long limits_exceeded[2];

// Counters
int msg;   // sent messages
int bpm_ibi_sample_counter;
long limits_exceeded_counter;

// int max_downlink_msgs;

// Shipment attempts
byte ship_attempt = 0;

// Last shipment timestamp
unsigned long shipment;

// Last ALARM_MSG timestamp
unsigned long amsg = 0;

/* Last timestamp of a shipment caused by
 * an emergency limit exceeded detection */
unsigned long elim_msg = 0;

// elim exceeded detection
byte elim = 0;

/* Emergency shipment's policy activation/deactivation timestamp
 * epol_act is also the timestamp of an emergency activation condition */
unsigned long epol_act, epol_deact;

// Recovery shipment policy activation timestamp
unsigned long rpol_act;


// Shipment policies (activated/deactivated)
byte epol = 0;
byte rpol = 0;


/* To differentiate between 'new emergencies'. If it is a new emergency,
 * the emergency shipment's policy will deliver reports faster than if
 * it's "actually the same emergency". The constant NEW_EMERG_DELAY 
 * differentiates between both situations. */
byte new_emergency = 1;
byte emergency = 0;


/* Emergency && Recovery shipment sequences */

// {30", 1', 2', 5', 2'30", 7', 5', 7'}
unsigned long critic_eseq [] = {30000,60000,120000,300000,150000,420000,300000,420000};
unsigned long non_critic_eseq [] = {90000,210000,540000,360000};
unsigned long rec_critic_eseq [] = {};
unsigned long rec_non_critic_eseq [] = {};


// Go through the previous sequences
byte critic_eseq_index = 0;
byte rec_critic_eseq_index = 0;
byte non_critic_eseq_index = 0;
byte rec_non_critic_eseq_index = 0;

/* Used to store the delay generated in shipment's logic
 * by shipment policies */
int acc_delay;

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

// Blink SENSORS_LED with every heartbeat
byte blink_on_pulse = 1;

// Indicates error on sigfox|sensors
byte sigfox_err = 0;
byte pulsesensor_err = 0;
byte temp_err = 0;


// byte first_ship = 1;

PulseSensorPlayground pulseSensor;
RTCZero rtc;
MAX30205 tempSensor;


void setup() {

  // Sigfox module id, used as a device identifier
  // const int device_id; // Does SigFox backend provide an id for Monitor service?

  Wire.begin();
  analogReadResolution(12);
  pinMode(INPUT_BUTTON_PIN, INPUT_PULLUP); // button press
  pinMode(SIGFOX_LED, OUTPUT);
  pinMode(SENSORS_LED, OUTPUT);
  pinMode(EMERGENCY_LED, OUTPUT);

  digitalWrite(EMERGENCY_LED, LOW);
  digitalWrite(SIGFOX_LED, LOW);

  attachInterrupt(digitalPinToInterrupt(INPUT_BUTTON_PIN), button_pressed, FALLING);

  // read from flash?
  msg = 0;
  shipment = 0;
  acc_delay = 0;
  //  max_downlink_msgs = ;
  epol_act = 0;
  epol_deact = 0;
  rpol_act = 0;
  
  reset_measures();
  set_rec_seqs();

  reset_buff(rec_buff);
  reset_buff(recv_buff);
  reset_buff(send_buff);


  /* Checking  Sigfox Module... */
  sigfox_check();
  if (!sigfox_err) {
    // device_id = SigFox.ID().toInt();
    // DOWNLINK_MSG (blink_on_pulse parameter, time, etc.)
    // blink_on_pulse = ; time = ; etc.
    SigFox.end(); // Send the module to sleep
    // All the power saving features are enabled.
    //SigFox.noDebug(); default?
  }
  else {
    // implement behaviour
  }


  // Configure the PulseSensor object
  pulseSensor.analogInput(PULSE_PIN);
  pulseSensor.setThreshold(PULSE_THRESHOLD);

  if (blink_on_pulse) // configured to blink on pulse
    pulseSensor.blinkOnPulse(SENSORS_LED); // blink SENSORS_LED with every heartbeat


  /* Checking sensors... */

  if (!pulseSensor.begin()) {
    pulsesensor_err = 1;
    pulsesensor_check(); // Initiate regular PulseSensor checking on error
  }

  if (!tempSensor.scanAvailableSensors())
    temp_err = 1;

  if (pulsesensor_err || temp_err) {
    if (blink_on_pulse)
      // Stop blinking bpm. Possible?
    flash_led(SENSORS_LED);
  }

  sched_shipment(SHIPMENT_INTERVAL, 0);
}


void set_rec_seqs() {
}


void reset_buff(byte arr[]) {
  for (byte i=0; i<(sizeof(arr)); i++)
    arr[i] = 0;
}


/* Flash EMERGENCY_LED on emergency or
 * SENSORS_LED/SIGFOX_LED on [sensors|sigfox module] error
 */
void flash_led(byte led) {

  unsigned long delay;
  byte timer, cond;
  byte *led_state;

  switch (led) {
    case EMERGENCY_LED:
      delay = EMERG_FLASH;
      led_state = &eled;
      cond = emergency_active();
      //timer = 0;
      break;
    case SIGFOX_LED:
      delay = BUG_FLASH;
      led_state = &sigfox_led;
      cond = sigfox_err;
      //timer = 1;
      break;
    case SENSORS_LED:
      delay = BUG_FLASH;
      led_state = &sensor_led;
      cond = (pulsesensor_err || temp_err);
      //timer = 2;
      break;
  }

  if (cond) {
    *led_state = !(*led_state);
    digitalWrite(led, *led_state);
    // timer::set(delay, flash_led(led));
    // timer::start();
  }
  else {
    *led_state = LOW;
    digitalWrite(led, LOW);
    // deactivate timer
    switch (led) {
      case EMERGENCY_LED:
        eflash = 0;
        break;
      case SIGFOX_LED:
        sigfox_flash = 0;
        break;
    }
  }
}


void pulsesensor_check() {

  byte round = 0;

  while (!pulseSensor.begin()) {
    if (++round==5) { // Ensure at least 5 calls
      // timer::set(CHECK_ERROR_COND, pulsesensor_check());
      // timer::start();
      return;
    }
  }
  pulsesensor_err = 0;
  // timer::stop
}


void sigfox_check() {

  byte round = 0;

  if (!sigfox_err) {
    if (init_sigfox_module()) {
      // timer::stop
      return;
    }
  }

  // Sigfox shield error
  sigfox_err = 1;
  if (!sigfox_flash) {
    sigfox_flash = 1;
    flash_led(SIGFOX_LED);
  }

  while (!SigFox.begin()) {
    if (++round==5) { // Ensure at least 5 calls
      // timer::set(CHECK_ERROR_COND, sigfox_check());
      // timer::start();
      return;
    }
    SigFox.reset();
  }
  sigfox_err = 0;
}


int init_sigfox_module() {
  if (SigFox.begin()) {
    sigfox_err = 0;
    return 1;
  }
  return 0;
}


/*
 * Attributes on flash:
 *   - maximum uplink messages per day included on data plan (max_uplink_msgs)
 *  // - maximum downlink messages per day included on data plan (max_downlink_msgs)
 *   - sent messages counter (msg)
 *   - accumulated shipment delay (acc_delay)
 *   - last shipment timestamp (shipment)
 *   - last Emergency shipment's policy activation timestamp (epol_act)
 *   - last Emergency shipment's policy deactivation timestamp (epol_deact)
*/

void update_flash(unsigned long shipment) {
}


void reset_measures() {
  // Initialize these vars to unlikely (impossible) values
  max_bpm = 0;
  min_bpm = 255;
  avg_bpm = 0.0;
  sd_bpm = -1.0;
  max_ibi = 0;
  min_ibi = 2000;
  avg_ibi = 0.0;
  sd_ibi = -1.0;

/* reset sampling buffers for a new sampling interval
  reset bpm_hist[];
  reset ibi_hist[];
*/

  for (byte i=0; i<2; i++)
    limits_exceeded[i] = 0;

  bpm_ibi_sample_counter = 0;
  limits_exceeded_counter = 0;
}


void handle_samples() {
}


// Returns accumulated delay on shipment's logic
int calc_delay() {

  int expected_msg, delay;
  float min_day;

  min_day =  rtc.getHours()*60 + rtc.getMinutes() + (((float)rtc.getSeconds())/60.0);
  expected_msg = ((int)(min_day/SHIPMENT_INTERVAL_MIN)) + REMAINING_MSG;

  if (msg < expected_msg)
    delay = 0;
  else {
    int rem_delay;
    rem_delay = (min_day - ((expected_msg - REMAINING_MSG) * SHIPMENT_INTERVAL_MIN))*60000;
    if (msg == expected_msg)
      delay = rem_delay;
    else
      delay = ((msg - expected_msg) * SHIPMENT_INTERVAL) - rem_delay;
  }
  return delay;
}


int predict_delay(byte eseq) {
}


unsigned long check_interval(unsigned long interval) {
  if (interval < MIN_SAMPLING_INTERVAL)
    return (unsigned long)MIN_SAMPLING_INTERVAL;
  return interval;
}


void resched_ship_pol(unsigned long delay) {

  byte *index, *rec_index;
  unsigned long *seq;

 // Initially schedule next shipment in (SHIPMENT_INTERVAL - delay) milliseconds
  sched_shipment(check_interval(SHIPMENT_INTERVAL - delay), 0);

  if (epol_active()) {

    if (new_emergency) {
      seq = critic_eseq;
      index = &critic_eseq_index;
      rec_index = &rec_critic_eseq_index;
    }
    else {
      seq = non_critic_eseq;
      index = &non_critic_eseq_index;
      rec_index = &rec_non_critic_eseq_index;
    }

    if ((*rec_index)==-1) {
      acc_delay = calc_delay();
      if (acc_delay>0) {
        *rec_index = (*index) -1;
        // delay_eseq = seq;
      }
    }

    if (*index == sizeof seq) {
      deact_emergency();
      deact_epol();
      if (acc_delay>0)
        act_rpol();
    }
    else {
      sched_shipment(check_interval(seq[*index] - delay), 0);
      (*index)++;
    }
  }

  if (rpol_active()) {

    if ((calc_delay())==0) {
      // rec_interrupted = 0;
      deact_rpol();
      sched_shipment(SHIPMENT_INTERVAL, 0);
    }
    else {
      if (new_emergency) {
        seq = rec_critic_eseq;
        index = &rec_critic_eseq_index;
      }
      else {
        seq = rec_non_critic_eseq;
        index = &rec_non_critic_eseq_index;
      }
      sched_shipment(check_interval(seq[*index] - delay), 0);
      if (++(*index) == sizeof seq)
        *index = 0;
    }
  }
}


void handle_failed_shipment() {

/*  byte reason_payload = ; */ // Payload already computed. Get this field from send_buff[].

  /* The reason why a shipment could fail is either
   * we've got to the maximum of messages in one day
   * or to the established top for shipment retries */

  // save payload on rec_buff on triggering emergency (Triggering emergency payload). Save limit vars??
/* Developing
 * if (reason_payload)
     for (byte i=0; i<SHIPMENT_BUFFER_SIZE; i++)
       rec_buff[i] = send_buff[i];
*/

  handle_samples();
  reset_measures();
  reset_buff(send_buff);
  resched_ship_pol(0);
  ship_attempt = 0;
}



void check_retry() {
  byte reason_payload = 0;  //DEVELOPING. SET TO ZERO FOR COMPILATION // Payload already computed. Get this field from send_buff[].
  if (ship_attempt == MAX_SHIPMENT_RETRIES)
    handle_failed_shipment();
  else {
    reset_buff(send_buff);
    sched_shipment(SHIPMENT_RETRY, reason_payload);
  }
}

// Simulate shipment
int mock_sigfox_call() {
  // simulate that it takes about 4 sec to send a message
  delay(4000);
  return random(0,99);
}

void send_measurements(byte reason_payload) {

  static float temp;
  static unsigned long delay;
  byte msg_type = REPORT_MSG;

  if (ship_attempt++==0) {
    byte i=0;

    delay = millis();
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
      tempSensor.shutdown();

      if (check_upper_limit(temp)) {
        // ship_timer.pause();
        limit_exceeded(UPPER_TEMP_MEASURE, 0);
      }
      else {
        if (check_lower_limit(temp)) {
          // ship_timer.pause();
          limit_exceeded(LOWER_TEMP_MEASURE, 0);
        }
      }
    }
  }

  /* Set message type */

  if (pulsesensor_err || temp_err)
    msg_type = ERROR_MSG;

  if (limits_exceeded_counter) { // msg_type == REPORT_MSG/ERROR_MSG
    if (msg_type==ERROR_MSG) {
      if (limits_exceeded[0] || limits_exceeded[1])
        msg_type = LIMITS_MSG; // if any of bpm limits exceeded, prioritize LIMITS_MSG
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


  if (bpm_ibi_sample_counter==0) // More secure than reading pulsesensor_err. (Division by 0 on avg_bpm computing)
    // avoid computing bpm. Configure payload accordinly (BPM field set to BPM_READING_ERR).

  // compute measurements
  // reason_payload{1:reason of emergency; 0: not the reason}
  // configure payload (based on msg_type and reason_payload and policies && emergency_active()) on send_buff
  // in case of LIMITS_MSG||ALARM_LIMITS_MSG send also limits_exceeded[] values


  if (msg == MAX_UPLINK_MSGS) {
    // sleep/continue sampling ??
    /* Payload already computed on send_buff */
    handle_failed_shipment();
    //rtc.standbyMode(); ?? // Send the board in standby mode.
    return;
  }


  /* Sigfox Module checking */

  if (!init_sigfox_module()) {
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

  /* Shipping...*/

  if (mock_sigfox_call()) {
    shipment = millis();
    msg++;
    button_pushed = 0;
    delay = shipment - delay;

    if (msg_type == ALARM_MSG || msg_type == ALARM_LIMITS_MSG) {
      amsg = shipment;
      if (emergency_active() && (!epol_active()))
        deact_emergency();
    }

    if (elim) {
      elim_msg = shipment;
      elim = 0;
    }

  // Developing
  /* if (rec_buff) (read_flash?) not empty, ship it here?
   *   if (sigfox call)
   *     reset_buff(rec_buff);
   *   else ?
   */

    reset_measures();
    reset_buff(send_buff);
    update_flash(shipment);
    resched_ship_pol(delay);
    ship_attempt = 0;
  }
  else check_retry();

  SigFox.end();
  pulseSensor.resume();
}


/*
void set_timer(byte timer, unsigned long ms, void *args) {
  // Reset timer, first of all. Pending?
  switch (timer) {
    case SHIPMENT_TIMER:
      // Reset timer, first of all. Pending?
      // if (ms==0) send_measurements(reason_payload)??? directamente, sin timer. ??
      // timer::set(ms, send_measurements(reason_payload));
      // timer::start();
      break;
  }
}
*/

void sched_shipment(unsigned long ms, byte reason_payload) {
  //set_timer(timer, ms, reason_payload);
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
  rec_critic_eseq_index = -1;
  rec_non_critic_eseq_index = -1;
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

  // Check whether there's already any accumulated delay
  int delay = calc_delay();

  // if eseq == CRITIC_ESEQ_REF
      // try critic_eseq (predict_delay(CRITIC_ESEQ_REF))
      // if success
          // return CRITIC_ESEQ_REF;

  // try non_critic_eseq (predict_delay(NON_CRITIC_ESEQ_REF))
      // if success
        // return NON_CRITIC_ESEQ_REF;
      // else return 0;
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
          // save rec_index
          deact_rpol();
          sched_shipment(0, 1);
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
            if (critic_eseq_index > ((sizeof critic_eseq)/2)) {
              // It's worth giving up critic_eseq
              critic_eseq_index = 0;
              new_emergency = 0;
            }
          }
          non_critic_eseq_index = 0;
          sched_shipment(0, 0);
        }
        /* If it's not possible to restart any of the eseqs,
         * just wait for the next scheduled shipment
         * on the ongoing eseq to notify it */
      }
    }
  }
  else // No policies active
    if (fire_epol(alarm))
      sched_shipment(0, 1);
}

// call ship_timer.resume() wherever you don't call send_measurements()
void handle_button_pushed() {

  act_emergency();

  if (!eflash) {
    eflash = 1;
    flash_led(EMERGENCY_LED);
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
  return (bpm > UPPER_BPM_ELIMIT);
}

byte check_lower_elimit(byte bpm) {
  return (bpm < LOWER_BPM_ELIMIT);
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


// Interrupts issue
// call ship_timer.resume() wherever you don't call send_measurements()
void limit_exceeded(byte measure, byte value) {

  byte both_exceeded, i;

  limits_exceeded_counter++;
  switch (measure) {
    case UPPER_BPM_MEASURE:
      i=0;
      break;
    case LOWER_BPM_MEASURE:
      i=1;
      break;
    default: // UPPER_TEMP_MEASURE || LOWER_TEMP_MEASURE
      return; // Do not continue, just count the temp limit exceeded
  }

  limits_exceeded[i]++;

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

  if (epol_active() || rpol_active())
    return;

  // No policies active at this point
  if (measure==UPPER_BPM_MEASURE)
    both_exceeded = limits_exceeded[i+1];
  else // LOWER_BPM_MEASURE
    both_exceeded = limits_exceeded[i-1];

  if (both_exceeded) {
    // maxs and mins of the same measure violated, trigger emergency
    if (fire_epol(0)) {
      act_emergency(); // do it here?
      sched_shipment(0, 1);
    }
    else {
      // implement behaviour
    }
    return;
  }

  if (limits_exceeded_counter > LIM_COUNT_EPOL_TRIGGERING) {
  /* Limits exceeded too many times.
   * Activate emergency shipment's policy. */
    if (fire_epol(0)) {
      act_emergency(); // do it here?
      sched_shipment(0, 1);
    }
    else {
      // implement behaviour
    }
  }
}


/* Overloaded function series to check
 * if any limit has been exceeded
 */
byte check_upper_limit(float temperature) {
  return (temperature > UPPER_TEMP_LIMIT);
}

byte check_lower_limit(float temperature) {
  return (temperature < LOWER_TEMP_LIMIT);
}

byte check_upper_limit(byte bpm) {
  return (bpm > UPPER_BPM_LIMIT);
}

byte check_lower_limit(byte bpm) {
  return (bpm < LOWER_BPM_LIMIT);
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

byte bytecast(int bpm) {
  if (bpm<0) return byte(0);
  else
    if (bpm>255) return byte(255);
  return byte(bpm);
}


void loop() {

  byte bpm;
  int ibi;

  if (button_flag) {
    if (!button_pushed) {
      // ship_timer.pause();
      button_pushed = 1;
      handle_button_pushed();
    }
    button_flag = 0;
  }
  
  /*
     See if a sample is ready from the PulseSensor.
     If USE_INTERRUPTS is false, this call to sawNewSample()
     will, if enough time has passed, read and process a
     sample (analog voltage) from the PulseSensor.
  */
  

  if (!pulsesensor_err && pulseSensor.sawNewSample()) {
    // reduce sampling (32kb SRAM) The largest sampling interval will be one defined in rec_seqs
    bpm = bytecast(pulseSensor.getBeatsPerMinute());
    ibi = pulseSensor.getInterBeatIntervalMs();
    /* proteger bpm_ibi_sample_counter? ; enviar bpm_ibi_sample_counter en el payload?
    bpm_hist[bpm_ibi_sample_counter] = bpm;
    ibi_hist[bpm_ibi_sample_counter] = ibi;
    bpm_ibi_sample_counter++; // count bpm and ibi readings
    */
    set_max_and_min(bpm, ibi);

  // check limits
    if (check_upper_limit(bpm)) {
      // ship_timer.pause();
      limit_exceeded(UPPER_BPM_MEASURE, bpm);
    }
    else
      if (check_lower_limit(bpm)) {
        // ship_timer.pause()
        limit_exceeded(LOWER_BPM_MEASURE, bpm);
      }
  }
}

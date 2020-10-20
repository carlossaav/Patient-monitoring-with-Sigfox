#define USE_ARDUINO_INTERRUPTS false
#include <PulseSensorPlayground.h>
#include <SigFox.h>
#include <RTCZero.h>
#include <Wire.h>
#include <Protocentral_MAX30205.h>


#define PULSE_PIN 0           // PulseSensor WIRE connected to ANALOG PIN 0
#define INPUT_BUTTON_PIN 0    // DIGITAL PIN 0 USED TO INTERRUPT whenever the button is pressed
//#define OUTPUT_BUTTON_PIN 2 // Alarm Button OUTPUT PIN (always outputs 3.3V)

#define SIGFOX_LED LED_BUILTIN
#define SENSORS_LED 12    // Blinks with every heartbeat
#define EMERGENCY_LED 10      // Used on emergencies

#define PULSE_THRESHOLD 2140   // Determine which Signal to "count as a beat" and which to ignore                               

#define UPPER_BPM_ELIMIT 150
#define LOWER_BPM_ELIMIT 50
#define UPPER_IBI_ELIMIT 3500
#define LOWER_IBI_ELIMIT 250
#define UPPER_TEMP_ELIMIT 38.0
#define LOWER_TEMP_ELIMIT 35.0


#define UPPER_BPM_LIMIT 125
#define LOWER_BPM_LIMIT 60
#define UPPER_IBI_LIMIT 3000
#define LOWER_IBI_LIMIT 500
#define UPPER_TEMP_LIMIT 37.5
#define LOWER_TEMP_LIMIT 35.5

#define MAX_BPM_SAMPLES 600
#define MAX_IBI_SAMPLES 600
#define MAX_TEMP_SAMPLES 11   // Measure temperature once per minute

#define RECEIVING_BUFFER_SIZE 8
#define SHIPMENT_BUFFER_SIZE 12

#define REPORT_MSG 0
#define ALARM_LIMITS_MSG 1
#define ALARM_MSG 2 
#define LIMITS_MSG 3
#define ERROR_MSG 4

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
#define TEST_ERROR_COND 5000
#define CHECK_ERROR_COND 15000

// keep the EMERGENCY_LED 2 seconds set to LOW && HIGH on emergency
#define EMERG_FLASH 2000
// keep the SIGFOX_LED||SENSORS_LED 4 seconds set to LOW && HIGH on error
#define BUG_FLASH 4000


#define SHIPMENT_TIMER 0


// To reset stored measurements
#define BPM_RESET 0
#define IBI_RESET 0
#define TEMP_RESET 0.0


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

/* measurements to send*/
byte max_bpm, min_bpm;
int max_ibi, min_ibi;
float avg_bpm, avg_ibi, sd_bpm, sd_ibi;
// variances/ranges?


/* sampling buffers */
byte bpm_hist[MAX_BPM_SAMPLES];
int ibi_hist[MAX_IBI_SAMPLES]; // evaluate data type
float temp_hist[MAX_TEMP_SAMPLES];

/* buffers for sending and receiving */
byte recv_buff[RECEIVING_BUFFER_SIZE];
byte send_buff[SHIPMENT_BUFFER_SIZE];

/* In case the failed shipment is
 * from the payload that triggered the emergency,
 * we'll save that payload */
byte rec_buff[SHIPMENT_BUFFER_SIZE];

/*
  For every body measurement limit, limits_exceeded stores how many
  times that limit has been exceeded.
  - limits_exceeded[0][1] for upper and lower bpm limit counts
  - limits_exceeded[2][3] for upper and lower ibi limit counts
  - limits_exceeded[4][5] for upper and lower temp limit counts
*/
int limits_exceeded[6];

/* counters */
int msg;   // sent messages
int bpm_ibi_sample_counter;
byte temp_sample_counter;
long limits_exceeded_counter;

// int max_downlink_msgs;

/* Last shipment timestamp */
unsigned long shipment;

/* Last ALARM_MSG timestamp */
unsigned long amsg = 0;

/* Last timestamp of a shipment caused by an emergency limit exceeded detection*/
unsigned long elim_msg = 0;

// elim exceeded detection
byte elim = 0;

/* Emergency shipment's policy activation/deactivation timestamp 
   epol_act is also the timestamp of an emergency activation condition */
unsigned long epol_act, epol_deact;

/* Limits exceeded and Recovery shipment policies activation timestamps */
unsigned long rpol_act;


// Shipment policies (activated/deactivated)
byte epol = 0;
byte rpol = 0;

/*
   To differentiate between 'new emergencies'. If it is a new emergency,
   the emergency shipment's policy will deliver reports faster than if
   it's "actually the same emergency". The constant NEW_EMERG_DELAY 
   differentiates between both situations.
*/
byte new_emergency = 1;
byte emergency = 0;

/* Emergency shipment sequences */

// {30", 1', 2', 5', 2'30", 7', 5', 7'}
int critic_eseq [] = {30000,60000,120000,300000,150000,420000,300000,420000};

int non_critic_eseq [] = {90000,210000,540000,360000};

int rec_critic_eseq [] = {};
int rec_non_critic_eseq [] = {};


// Go through the previous sequences
byte critic_eseq_index = 0;
byte rec_critic_eseq_index = 0;
byte non_critic_eseq_index = 0;
byte rec_non_critic_eseq_index = 0;

/* used to store the delay generated in shipment's logic
 * by shipment policies */
int acc_delay;

/* Before getting into any of the emergency sequences, we must
 * check whether it's going to be possible to recover the
 * delay generated by those sequences
 */
int potential_delay = 0;

// To notice whether the user pressed the emergency button
volatile byte button_flag = 0;
byte button_pushed = 0;

// Led states
byte eled = LOW;
byte sigfox_led = LOW;
byte sensor_led = LOW;

// Indicates whether eled is flashing or not 
byte eflash = 0;

byte sigfox_err = 0;
byte sensor_err = 0;

byte ship_attempt = 0;
// byte first_ship = 1;

PulseSensorPlayground pulseSensor;
RTCZero rtc;
MAX30205 tempSensor;

void setup() {

  // Sigfox module id, used as a device identifier
  // const int device_id; // Does SigFox backend provide an id for Monitor service?

  analogReadResolution(12);
  pinMode(INPUT_BUTTON_PIN, INPUT_PULLUP); // button press
//  pinMode(OUTPUT_BUTTON_PIN, OUTPUT);  
  pinMode(SIGFOX_LED, OUTPUT);
  pinMode(SENSORS_LED, OUTPUT);
  pinMode(EMERGENCY_LED, OUTPUT);

  digitalWrite(EMERGENCY_LED, LOW);
  //  digitalWrite(OUTPUT_BUTTON_PIN, HIGH);
  digitalWrite(SIGFOX_LED, LOW);
  sigfox_check();
  if (sigfox_err) {
    flash_led(SIGFOX_LED);
    // implement behaviour
  }
  else {
    // device_id = SigFox.ID().toInt();
    SigFox.end(); // Send the module to sleep
    // All the power saving features are enabled.
    //SigFox.noDebug(); default?
  }

  // read from flash?
  acc_delay = 0;
  msg = 0;
  shipment = 0;
//  max_downlink_msgs = ;
  epol_act = 0;
  epol_deact = 0;
  rpol_act = 0;

  reset_measures();
  set_rec_eseqs();

  attachInterrupt(digitalPinToInterrupt(INPUT_BUTTON_PIN), button_pressed, FALLING);

  // Configure the PulseSensor object
  pulseSensor.analogInput(PULSE_PIN);
  pulseSensor.blinkOnPulse(SENSORS_LED);
  pulseSensor.setThreshold(PULSE_THRESHOLD);

  Wire.begin();
  sensor_check(0);
  sensor_check(1);

  // set also RTC alarm to call get_temperature()
  sched_shipment(SHIPMENT_INTERVAL, REPORT_MSG, 0);
}


void set_rec_eseqs() {
}


/* Flash EMERGENCY_LED on emergency or
   SENSORS_LED/SIGFOX_LED on [sensors|sigfox module] error
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
      cond = sensor_err;
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
    // deactivate timer
    if (led == EMERGENCY_LED)
      eflash = 0;
    *led_state = LOW;
    digitalWrite(led, LOW);
  }
}


/* PulseSensor and Temperature sensor checking.
 * sensor parameter equals to 0 for PulseSensor
 * and 1 for the Temperature sensor.
 * Returns 1 if everything is ok,
 * otherwise returns 0 */
byte sensor_check(byte sensor) {
}


void sigfox_check() {

  unsigned long tstamp;

  if (!sigfox_err) {
    if (init_sigfox_module()) {
      // deactivate timer
      return;
    }
  }

  // Sigfox shield error
  tstamp = millis();
  sigfox_err = 1;
  while (!SigFox.begin()) {
    SigFox.reset();
    if ((millis() - tstamp) >= TEST_ERROR_COND) {
      // timer::set(CHECK_ERROR_COND, sigfox_check());
      // timer::start();
      return;
    }
  }
  sigfox_err = 0;
  // timer::stop?
}


int init_sigfox_module() {
  if (SigFox.begin()) {
    if (sigfox_err)
      sigfox_err = 0;
    return 1;
  }
  else return 0;
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
  max_bpm = BPM_RESET;
  min_bpm = BPM_RESET + 255;
  avg_bpm = float(BPM_RESET);
  sd_bpm = -1.0;
  max_ibi = IBI_RESET;
  min_ibi = IBI_RESET + 2000;
  avg_ibi = float(IBI_RESET);
  sd_ibi = -1.0;
  //variances?
  
  // reset sampling buffers for a new sampling interval
  for (int i=0; i<MAX_BPM_SAMPLES; i++)
    bpm_hist[i] = BPM_RESET;
  for (int i=0; i<MAX_IBI_SAMPLES; i++)
    ibi_hist[i] = IBI_RESET;
  for (int i=0; i<MAX_TEMP_SAMPLES; i++)
    temp_hist[i] = TEMP_RESET;
  
  // reset pending measurements exceeded
  for (int i=0; i<6; i++)
    limits_exceeded[i] = 0;

  // reset sending and receiving buffers
  for (int i=0; i<SHIPMENT_BUFFER_SIZE; i++)
    send_buff[i] = 0; // think it twice
  for (int i=0; i<RECEIVING_BUFFER_SIZE; i++)
    recv_buff[i] = 0; // think it twice

  bpm_ibi_sample_counter = 0;
  temp_sample_counter = 0;
  limits_exceeded_counter = 0;
}



// triggered once per minute (by timer?) to measure body temperature
void get_temperature() {
  if (sensor_check(1)) {
    float temp;
    tempSensor.begin();
    temp = tempSensor.getTemperature();
    tempSensor.shutdown();
    temp_hist[temp_sample_counter] = temp;
    temp_sample_counter++;

    if (check_upper_limit(temp)) {
      // ship_timer.pause();
      limit_exceeded(4, temp);
    }
    else
      if (check_lower_limit(temp)) {
        // ship_timer.pause();
        limit_exceeded(5, temp);
      }
  }
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


unsigned long check_interval(int interval) {
  if (interval < MIN_SAMPLING_INTERVAL)
    return (unsigned long)MIN_SAMPLING_INTERVAL;
  return (unsigned long)interval;
}


void resched_ship_pol() {

  byte *index, *rec_index;
  int *seq;

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
      sched_shipment(seq[*index], REPORT_MSG, 0);
      (*index)++;
    }
  }

  if (rpol_active()) {

    if ((calc_delay())==0) {
      // rec_interrupted = 0;
      deact_rpol();
      sched_shipment(SHIPMENT_INTERVAL, REPORT_MSG, 0);
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
      sched_shipment(seq[*index], REPORT_MSG, 0);
      if (++(*index) == sizeof seq)
        *index = 0;
    }
  }
}


void handle_failed_shipment(byte reason_payload) {
  // Just progress to the next sampling interval
  sched_shipment(check_interval(SHIPMENT_INTERVAL-((ship_attempt-1)*SHIPMENT_RETRY)), REPORT_MSG, 0);

  // if (reason_payload)
    // do_computing/copy buff from send_buff
    // save payload on rec_buff
  handle_samples();
  reset_measures();
  resched_ship_pol();
  ship_attempt = 0;
}



void send_measurements(byte msg_type, byte reason) {

  // Initially schedule next shipment in SHIPMENT_INTERVAL milliseconds
  if (ship_attempt++==0)
    sched_shipment(SHIPMENT_INTERVAL, REPORT_MSG, 0);

  if (msg == MAX_UPLINK_MSGS) {
    // sleep/continue sampling
  }

  if (!init_sigfox_module()) {
    if (!sigfox_err) {
      // Initiate regular sigfox module checking
      sigfox_check();
      if (sigfox_err) {
        flash_led(SIGFOX_LED);
        // Hopefully, it's a temporary failure on Sigfox module
        if (ship_attempt == MAX_SHIPMENT_RETRIES)
          handle_failed_shipment(reason);
        else
          sched_shipment(SHIPMENT_RETRY, msg_type, reason);
        return;
      }
      /* Atfter first checking, sigfox module has been initialized successfully.
       * Continue with the shipment */
    }
    else {
      /* Regular sigfox module checking already in progress.
       * Hopefully, it's a temporary failure on Sigfox module */
      if (ship_attempt == MAX_SHIPMENT_RETRIES)
        handle_failed_shipment(reason);
      else
        sched_shipment(SHIPMENT_RETRY, msg_type, reason);
      return;
    }
  }

  if (msg_type != LIMITS_MSG) {
    // check if any measurement has been exceeded
    if (limits_exceeded_counter) {
      switch (msg_type) {
        case ALARM_MSG:
          msg_type = ALARM_LIMITS_MSG;
          break;
        case REPORT_MSG:
          msg_type =  LIMITS_MSG;
          break;
       // case ERROR_MSG??
      }
    }
  }

  if (button_pushed) {
    switch (msg_type) {
      case LIMITS_MSG:
        msg_type = ALARM_LIMITS_MSG;
        break;
      default: // Only makes sense for REPORT_MSG. msg_type == ALARM_MSG/REPORT_MSG/ERROR_MSG
        msg_type =  ALARM_MSG;
        break;
    }
  }

  // compute measurements
  // REason{1:reason of emergency; 0: not the reason}
  // configure payload (based on msg_type and reason and policies && emergency_active()) on send_buff
  // save payload in recovery buff on triggering emergency (Triggering emergency payload) Do this
  // with every payload?. Save limit vars.
  // in case of LIMITS_MSG||ALARM_LIMITS_MSG send also limits_exceeded[] values

  pulseSensor.pause();
/*  
  if (! sigfox call) {
    // Failed shipment
    SigFox.end();
    pulseSensor.resume();
    if (ship_attempt == MAX_SHIPMENT_RETRIES)
      handle_failed_shipment(reason);
    else
      sched_shipment(SHIPMENT_RETRY, msg_type, reason);
    return;
  }
*/
  shipment = millis();
  msg++;
  button_pushed = 0;

  if (msg_type == ALARM_MSG || msg_type == ALARM_LIMITS_MSG) {
    amsg = shipment;
    if (emergency_active() && (!epol_active()))
      deact_emergency();
  }

  if (elim) {
    elim_msg = shipment;
    elim = 0;
  }

  SigFox.end();
  update_flash(shipment);
  reset_measures();
  resched_ship_pol();
  ship_attempt = 0;
  pulseSensor.resume();
}


/*
void set_timer(byte timer, unsigned long ms, void *args) {
  // Reset timer, first of all. Pending?
  switch (timer) {
    case SHIPMENT_TIMER:
      // timer::set(ms, send_measurements(msg_type, reason));
      // timer::start();
      break;
  }
}
*/

void sched_shipment(unsigned long ms, byte msg_type, byte reason) {
  //set_timer(timer, ms, &msg_type, reason);
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



/* When an emergency is raised, Limits_exceeded policy
 * is automatically deactivated.
 * Returns 1 if epol has been activated,
 * otherwise returns 0.
 */
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


// call ship_timer.resume() wherever you don't call send_measurements()
void handle_button_pushed() {

  act_emergency();
  
  if (!eflash) {
    eflash = 1;
    flash_led(EMERGENCY_LED);
  }
  
  if ((rpol_active()) || (epol_active())) {
    if (amsg < epol_act) {
      // No ALARM_MSG has been sent in the last emergency policy.
      if (rpol_active()) {
        if (fire_epol(1)) {
          // save rec_index
          deact_rpol();
          send_measurements(ALARM_MSG, 1);
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
          send_measurements(ALARM_MSG, 0);
        }
        /* If it's not possible to restart any of the eseqs,
         * just wait for the next scheduled shipment on the ongoing eseq
         * to notify an ALARM_MSG */
      }
    }
  }
  else // No policies active
    if (fire_epol(1))
      send_measurements(ALARM_MSG, 1);

    // else: Emergency active but no policies active

    /* If it's not possible to activate epol,
     * just wait for the next scheduled shipment
     * to notify an ALARM_MSG. */ 
}


/* Interrupt Service Routine button_pressed(),
 * triggered whenever the user pushes the emergency button
 */
void button_pressed() {
  button_flag = 1;
}


/* Overloaded function series to check if any 
 * elimit has been exceeded
 */
byte check_upper_elimit(float temperature) {
  return (temperature > UPPER_TEMP_ELIMIT);
}

byte check_upper_elimit(byte bpm) {
  return (bpm > UPPER_BPM_ELIMIT);
}

byte check_upper_elimit(int ibi) {
  return (ibi > UPPER_IBI_ELIMIT);
}

byte check_lower_elimit(float temperature) {
  return (temperature < LOWER_TEMP_ELIMIT);
}

byte check_lower_elimit(byte bpm) {
  return (bpm < LOWER_BPM_ELIMIT);
}

byte check_lower_elimit(int ibi) {
  return (ibi < LOWER_IBI_ELIMIT);
}


byte check_elimits(byte measure, float value) {
  switch (measure) {
    case 0:
      return check_upper_elimit(bytecast(int(value)));
    case 1:
      return check_lower_elimit(bytecast(int(value)));
    case 2:
      return check_upper_elimit(int(value));
    case 3:
      return check_lower_elimit(int(value));      
    case 4:
      return check_upper_elimit(value);
    case 5:
      return check_lower_elimit(value);
  }
}


// Interrupts issue
// call ship_timer.resume() wherever you don't call send_measurements()
void limit_exceeded(byte measure, float value) {

  byte both_exceeded;

  limits_exceeded[measure]++;
  limits_exceeded_counter++;

  if (check_elimits(measure, value)) {

    if (elim)
      /* Whatever elim has been exceeded, there's been
       * a previous elim before this one took place
       * that hasn't been attended yet. */
      return;

    elim = 1;
    act_emergency();

    if ((rpol_active()) || (epol_active())) {
      if (elim_msg < epol_act) {
        // No LIMIMTS_MSG caused by an elim has been sent in the last emergency policy.
        if (rpol_active()) {
          if (fire_epol(1)) {
            deact_rpol();
            send_measurements(LIMITS_MSG, 1);
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
            send_measurements(LIMITS_MSG, 0);
          }
          /* If it's not possible to restart any of the eseqs,
           * just wait for the next scheduled shipment
           * on the ongoing eseq to notify an ALARM_MSG */
        }
      }
    }
    else // No policies active
      if (fire_epol(1))
        send_measurements(LIMITS_MSG, 1);
  }

  if (epol_active() || rpol_active())
    return;

  // No policies active at this point
  if (measure%2)
    both_exceeded = limits_exceeded[measure-1];
  else
    both_exceeded = limits_exceeded[measure+1];

  if (both_exceeded) {
    // maxs and mins of the same measure violated, trigger emergency
    if (fire_epol(0)) {
      act_emergency(); // do it here?
      send_measurements(LIMITS_MSG, 1);
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
      send_measurements(LIMITS_MSG, 1);
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

  if (pulseSensor.sawNewSample()) {
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
      limit_exceeded(0, bpm);
    }
    else
      if (check_lower_limit(bpm)) {
        // ship_timer.pause()
        limit_exceeded(1, bpm);
      }

/*
    if (check_upper_limit(ibi)) {
      // ship_timer.pause();
      limit_exceeded(2, ibi);
    }
    else
      if (check_lower_limit(ibi)) {
        // ship_timer.pause();
        limit_exceeded(3, ibi);
      }
*/
  }
}
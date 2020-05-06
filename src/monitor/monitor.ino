#define USE_ARDUINO_INTERRUPTS false
#include <PulseSensorPlayground.h>
#include <SigFox.h>

#define PULSE_PIN 0       // PulseSensor WIRE connected to ANALOG PIN 0
#define TEMPERATURE_PIN 1 // LM-35 signal connected to ANALOG PIN 1
#define BUTTON_PIN 2      // Alarm Button pin connected to ANALOG PIN 2

#define PULSE_THRESHOLD 535 // Determine which Signal to "count as a beat" and which to ignore                               

#define PULSESENSOR_LED  // indicates that pulsesensor is not working

#define MAX_BPM_LIMIT 125
#define MIN_BPM_LIMIT 60
#define MAX_IBI_LIMIT 
#define MIN_IBI_LIMIT 
#define MAX_TEMP_LIMIT 37.5
#define MIN_TEMP_LIMIT 35.5

#define BPM_IBI_BUFFER_SIZE 
#define TEMP_BUFFER_SIZE 12 // Measure temperature once per minute
#define RECEIVING_BUFFER_SIZE 8
#define SHIPMENT_BUFFER_SIZE 12

#define REPORT_MSG
#define EMERGENCY_MSG
#define LIMITS_MSG
#define EMERGENCY_LIMITS_MSG
#define ERROR_MSG

#define EMERGENCY_MSG_DELAY
#define LIMIT_MSG_DELAY
#define ERROR_MSG_DELAY

#define SHIPMENT_INTERVAL 720000  // 12 min
#define SAMPLING_DELAY
//#define ERROR_CONDITION 60000

#define MAX_SHIPMENT_ATTEMPTS // In case of failed shipments

// To reset stored measurements
#define BPM_RESET 0
#define IBI_RESET -1
#define TEMP_RESET -200.0

/** Variables **/

struct msg_format {
}

struct limit {
//  String measure;
  float worse_value;
  int count;
}

/* some measurements */
volatile byte max_bpm_value, min_bpm_value;
volatile int max_ibi_value, min_ibi_value;

// missing temperature vars

/* sampling buffers */
volatile byte bpm_hist[BPM_IBI_BUFFER_SIZE];
volatile int ibi_hist[BPM_IBI_BUFFER_SIZE]; // evaluate data type
volatile float temp_hist[TEMP_BUFFER_SIZE];

/* buffers for sending and receiving */
byte recv_buff[RECEIVING_BUFFER_SIZE];
byte send_buff[SHIPMENT_BUFFER_SIZE];

// maxs and mins of every body measure. For LIMITS_MSG purposes
struct limit pending_buff[6];

/* counters */
volatile byte count_messages; // sent messages
volatile int bpm_ibi_sample_counter; // for sampling between shipments
volatile short temp_sample_counter;

/* shipment timestamps */
volatile unsigned long last_msg;
volatile unsigned long emergency_msg_tstamp;
volatile unsigned long limit_exceeded_msg_tstamp;
volatile unsigned long err_msg_tstamp;

volatile unsigned long err_cond_tstamp;

// PulseSensorPlayground object
PulseSensorPlayground pulseSensor;

void setup() {

  // Sigfox module id, used as a device identifier
  const int device_id;
  byte first_shipment = 1;

  err_cond_tstamp = 0;
  err_msg_tstamp = 0; // read from flash?

  if !(init_sigfox_module()) {
    // implement behaviour
    return;
  }

  device_id = SigFox.ID().toInt();
  SigFox.end(); // Send the module to sleep

  // All the power saving features are enabled.
  //SigFox.noDebug(); default?

  count_messages = 0; // read from flash?

  // read timestamps from flash?
  last_msg = 0;
  emergency_msg_tstamp = 0;
  limit_exceeded_msg_tstamp = 0;

  attachInterrupt(digitalPinToInterrupt(1), button_pushed, RISING);
  attachInterrupt(digitalPinToInterrupt(4), get_temperature, RISING);

  pinmode(TEMPERATURE_PIN,INPUT); // LM-35 signal
  pinmode(BUTTON_PIN,INPUT); // Alarm button

  // Configure the PulseSensor object, by assigning our variables to it. 
  pulseSensor.analogInput(PULSE_PIN);
  pulseSensor.blinkOnPulse(LED_BUILTIN);  //auto-magically blink Arduino's LED with heartbeat.
  pulseSensor.setThreshold(PULSE_THRESHOLD);

  if (!pulseSensor.begin()) {
    err_cond_tstamp = milis();
    send_error_report();
    while ((millis() - err_cond_tstamp) < ERROR_CONDITION)
      flash_led(PULSESENSOR_LED);
  }

  reset_vars(BPM_IBI_BUFFER_SIZE, TEMP_BUFFER_SIZE);
}

// blocking function
// Flash LED_BUILTIN||PULSESENSOR_LED to show things didn't work.
void flash_led(int led) {
  short miliseconds;

  if (led == LED_BUILTIN)
    miliseconds = 3000;
  else
    miliseconds = 5000;

  digitalWrite(led, LOW);
  delay(miliseconds);
  digitalWrite(led, HIGH);
  delay(miliseconds);
}


void reset_vars(int bpm_ibi_samples, int temp_samples) {

  // Initialize these vars to unlikely (impossible) values
  max_bpm_value = BPM_RESET;
  min_bpm_value = BPM_RESET + 255;
  max_ibi_value = IBI_RESET;
  min_ibi_value = IBI_RESET + ?;
  average_bpm = BPM_RESET;
  average_ibi = IBI_RESET;
  typical_deviation_bpm = -1.0;
  typical_deviation_ibi = -1.0;

  // missing temperature vars

  // reset sampling buffers for a new sampling interval
  for (int i=0; i<bpm_ibi_samples; i++)
    bpm_hist[i] = BPM_RESET;
  for (int i=0; i<bpm_ibi_samples; i++)
    ibi_hist[i] = IBI_RESET;
  for (int i=0; i<temp_samples; i++)
    temp_hist[i] = TEMP_RESET;
  for (int i=0; i<6; i++) {
    pending_buff[i].worse_value = -1.0; // think it twice
    pending_buff[i].count = 0;
  }

  // reset sending and receiving buffers
  for (int i=0; i<SHIPMENT_BUFFER_SIZE; i++)
    send_buff[i] = 0; // think it twice
  for (int i=0; i<RECEIVING_BUFFER_SIZE; i++)
    recv_buff[i] = 0; // think it twice

  bpm_ibi_sample_counter = 0;
  temp_sample_counter = 0;
}


/*
  Attributes on flash:
    - data plan (max_messages)
    - sent messages counter (count_messages)
    - accumulated shipment delay (used when shipment interval <12 min, i.e. button_pushed)
    - last message timestamp (last_msg)
    - last EMERGENCY_MSG timestamp (emergency_msg_tstamp)
    - last LIMITS_MSG timestamp (limit_exceeded_msg_tstamp)
    - last ERROR_MSG timestamp (err_msg_tstamp)
*/

void update_flash(unsigned long last_msg, int max_messages) {
}

/*
int init_sigfox_module() {
  // Sigfox shield error
  if (!SigFox.begin()) {
    err_cond_tstamp = milis();
    while ((millis() - err_cond_tstamp) < ERROR_CONDITION)
      flash_led(LED_BUILTIN);
    return 0;
  }
  return 1;
}
*/

/*
  Returns 1 on successful shipment,
  otherwise returns 0.
*/
/*
byte send_msg() {
  byte avg_bpm;
  int avg_ibi;
  float typical_deviation_bpm, typical_deviation_ibi;
// variances?
  byte attempts;

  if !(init_sigfox_module()) {
    // implement behaviour
    return 0;
  }

  // compute averages, typical deviation, etc. 

  // limits_exceeded at some point but couldnt send measures
  if (pending_buff no vacío) // consider first_shipment
    case
      first 3 bits == EMERGENCY_MSG
        set first 3 bits to EMERGENCY_LIMITS_MSG
      first 3 bits == REPORT_MSG
        set first 3 bits to LIMITS_MSG

  // introduce data on send_buff

  attempts = 1;
  while (attempts <= MAX_SHIPMENT_ATTEMPTS) {
    if (call to sigfox backend) {
      last_msg = millis();
      if (first_shipment) {
        // wait response (x time), get data
        if response
          first_shipment = 0;
      }
      break;
    }
    if (++attempts > MAX_SHIPMENT_ATTEMPTS)
      break; // avoid last delay
    // delay next attempt
  }

  // Failed shipment. Samples lost?
  if (attempts > MAX_SHIPMENT_ATTEMPTS) {
    // implement behaviour
    return 0;
  }


  if (first 3 bits == EMERGENCY_LIMITS_MSG) {
    emergency_msg_tstamp = last_msg;
    limit_exceeded_msg_tstamp = last_msg;
  }
  else
    if (first 3 bits == LIMITS_MSG)
      limit_exceeded_msg_tstamp = last_msg;

  count_messages++;
  update_flash(last_msg, max_messages);
  reset_vars(bpm_ibi_sample_counter, temp_sample_counter);
  SigFox.end();

  return 1;
}


void handle_failed_shipment(byte msg_type) {
}

void set_msg_type(byte msg_type) {
  // set first three bits to msg_type on send_buff
  if (first_shipment)
    // set first three bits to msg_type + initial_msg on send_buff
}

*/

/*
  Interrupt Service Routines:
    - get_temperature() -> triggered once per second to measure body temperature
    - button_pushed() -> triggered whenever the user pushes the emergency button
    - send_common_report() -> triggered every SHIPMENT_INTERVAL miliseconds to send biometric data
                              to the Sigfox backend
*/

/*
void get_temperature() {
  float temperature = // Compute temperature on TEMPERATURE_PIN;
  temp_hist[temp_sample_counter] = temperature;
  temp_sample_counter++;

  if (check_value(temperature))
    limits_exceeded();
}


void button_pushed() {
  // check if an EMERGENCY_MSG has been sent
  if (emergency_msg_tstamp != 0)
    if ((millis() - emergency_msg_tstamp) < EMERGENCY_MSG_DELAY))
      return;

  if (count_messages == max_messages) {
    handle_failed_shipment(EMERGENCY_MSG);
    return;
  }
  set_msg_type(EMERGENCY_MSG);
  if !(send_msg())
    handle_failed_shipment(EMERGENCY_MSG);
}

void send_common_report() {
  if (count_messages == max_messages) {
    handle_failed_shipment(REPORT_MSG);
    return;
  }
  set_msg_type(REPORT_MSG);
  if !(send_msg())
    handle_failed_shipment(REPORT_MSG);
}


void send_error_report() {
  // check if an ERROR_MSG has been sent
  if (err_msg_tstamp != 0)
    if ((millis() - err_msg_tstamp) < ERROR_MSG_DELAY))
      return;

  if (count_messages == max_messages) {
    handle_failed_shipment(ERROR_MSG);
    return;
  }
  set_msg_type(ERROR_MSG);
  if !(send_msg())
    handle_failed_shipment(ERROR_MSG);
}


void limits_exceeded() {
  // check if a LIMITS_MSG has been sent
  if (limit_exceeded_msg_tstamp != 0)
    if ((millis() - limit_exceeded_msg_tstamp) < LIMIT_MSG_DELAY))
      return;

  if (count_messages == max_messages) {
    handle_failed_shipment(LIMITS_MSG);
    return;
  }
  set_msg_type(LIMITS_MSG);
  if !(send_msg())
    handle_failed_shipment(LIMITS_MSG);
}
*/

/*
  check_value() and check_values():
    Both return 0 for values within the range,
    and 1 when limits have been exceeded
*/
byte check_value(float temperature) {
  if ((temperature > MAX_TEMP_LIMIT) || (temperature < MIN_TEMP_LIMIT))
    return 1;
  return 0;
}

byte check_values(byte bpm, int ibi) {
  if (((bpm > MAX_BPM_LIMIT) || (bpm < MIN_BPM_LIMIT)) ||
      ((ibi > MAX_IBI_LIMIT) || (ibi < MIN_IBI_LIMIT)))
    return 1;
  return 0;
}

void set_max_and_min(byte bpm, int ibi) {
  if (bpm > max_bpm_value)
    max_bpm_value = bpm;
  else
    if (bpm < min_bpm_value)
      min_bpm_value = bpm;

  if (ibi > max_ibi_value)
    max_ibi_value = ibi;
  else
    if (ibi < min_ibi_value)
      min_ibi_value = ibi;
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

  byte bpm;
  int ibi;

  /*
     See if a sample is ready from the PulseSensor.
     If USE_INTERRUPTS is false, this call to sawNewSample()
     will, if enough time has passed, read and process a
     sample (analog voltage) from the PulseSensor.
  */

  if (pulseSensor.sawNewSample()) {
    // reduce sampling (32K SRAM)
    bpm = bytecast(pulseSensor.getBeatsPerMinute());
    ibi = pulseSensor.getInterBeatIntervalMs();
    bpm_hist[bpm_ibi_sample_counter] = bpm;
    ibi_hist[bpm_ibi_sample_counter] = ibi;
    bpm_ibi_sample_counter++; // count bpm and ibi readings

    set_max_and_min(bpm, ibi);

    // check if bpm or ibi values exceeded limits
    if (check_values(bpm, ibi))
      limits_exceeded();

    /*******
     Here is a good place to add code that could take up
     to a milisecond or so to run.
     *******/
  }

  if (millis() - last_msg >= SHIPMENT_INTERVAL)
    send_common_report();
}
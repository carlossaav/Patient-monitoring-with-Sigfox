#define USE_ARDUINO_INTERRUPTS false
#include <PulseSensorPlayground.h>
#include <SigFox.h>
#include <MsTimer2.h>

#define PULSE_PIN 0       // PulseSensor WIRE connected to ANALOG PIN 0
#define TEMPERATURE_PIN 1 // LM-35 signal connected to ANALOG PIN 1
#define BUTTON_PIN      // Alarm Button pin connected to

#define PULSE_THRESHOLD 535 // Determine which Signal to "count as a beat" and which to ignore                               

#define PULSESENSOR_LED  // indicates that pulsesensor is not working

#define UPPER_BPM_LIMIT 125
#define LOWER_BPM_LIMIT 60
#define UPPER_IBI_LIMIT 
#define LOWER_IBI_LIMIT 
#define UPPER_TEMP_LIMIT 37.5
#define LOWER_TEMP_LIMIT 35.5

#define MAX_BPM_SAMPLES 
#define MAX_IBI_SAMPLES
#define MAX_TEMP_SAMPLES 12 // Measure temperature once per minute

#define RECEIVING_BUFFER_SIZE 8
#define SHIPMENT_BUFFER_SIZE 12

#define REPORT_MSG
#define EMERGENCY_LIMITS_MSG
#define EMERGENCY_MSG
#define LIMITS_MSG
#define ERROR_MSG

//#define REPORT_MSG_DELAY
#define EMERGENCY_MSG_DELAY 180000 // wait 3 mins before shipping another EMERGENCY_MSG
#define LIMITS_MSG_DELAY 300000 // wait 5 mins here
//#define ERROR_MSG_DELAY

#define SHIPMENT_INTERVAL 720000  // 12 min
//#define SAMPLING_DELAY
#define TEST_ERROR_CONDITION 15000
#define BUG_FLASH 3000 // keep the led 3000 milliseconds set to LOW or HIGH on error

#define MAX_SHIPMENT_ATTEMPTS // In case of failed shipments

// To reset stored measurements
#define BPM_RESET 0
#define IBI_RESET 0
#define TEMP_RESET 0.0

/** Variables **/

struct msg_format {
}

/* measurements to send*/
volatile byte max_bpm, min_bpm;
volatile int max_ibi, min_ibi;
volatile float avg_bpm, avg_ibi, sd_bpm, sd_ibi;
// variances/modes?


/* sampling buffers */
volatile byte bpm_hist[MAX_BPM_SAMPLES];
volatile int ibi_hist[MAX_IBI_SAMPLES]; // evaluate data type
volatile float temp_hist[MAX_TEMP_SAMPLES];

/* buffers for sending and receiving */
byte recv_buff[RECEIVING_BUFFER_SIZE];
byte send_buff[SHIPMENT_BUFFER_SIZE];

/*
  For every body measurement limit, limits_exceeded_counter stores how many
  times that limit has been exceeded. For LIMITS_MSG purposes.
  - limits_exceeded_counter[0][1] for upper and lower bpm limit counts
  - limits_exceeded_counter[2][3] for upper and lower ibi limit counts
  - limits_exceeded_counter[4][5] for upper and lower temp limit counts
*/
volatile int limits_exceeded_counter[6];

/* counters */
volatile byte count_messages; // sent messages
volatile short bpm_ibi_sample_counter;
volatile byte temp_sample_counter;

/* shipment timestamps */
volatile unsigned long last_msg;
volatile unsigned long emergency_msg_tstamp;
volatile unsigned long limit_exceeded_msg_tstamp;
volatile unsigned long err_msg_tstamp;

volatile unsigned long sigfox_err_tstamp;

/* used when shipment occured before SHIPMENT_INTERVAL (e.g. button_pushed) */
volatile unsigned long acc_shipment_delay;

/* For failed EMERGENCY_MSG shipments */
volatile byte failed_emergency_msg;

PulseSensorPlayground pulseSensor;


void setup() {

  // Sigfox module id, used as a device identifier
  const int device_id; // Does SigFox backend provide an id for Monitor service?
  byte first_shipment = 1;
  unsigned long pulse_sensor_err_tstamp = 0;

  err_msg_tstamp = 0; // read from flash?
  sigfox_err_tstamp = 0;

  if !(init_sigfox_module()) {
    // implement behaviour
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
  acc_shipment_delay = 0;

  failed_emergency_msg = 0;

  pinmode(TEMPERATURE_PIN,INPUT); // LM-35 signal
  pinmode(BUTTON_PIN,INPUT); // button press
  attachInterrupt(digitalPinToInterrupt(BUTTON_PIN), button_pushed, RISING);

  // Configure the PulseSensor object, by assigning our variables to it. 
  pulseSensor.analogInput(PULSE_PIN);
  pulseSensor.blinkOnPulse(PULSESENSOR_LED);  //auto-magically blink Arduino's LED with heartbeat.
  pulseSensor.setThreshold(PULSE_THRESHOLD);

  reset_vars();
  /*
  while (!pulseSensor.begin()) {
    if !(pulse_sensor_err_tstamp)
      pulse_sensor_err_tstamp = millis();
    send_error_report();
    while ((millis() - pulse_sensor_err_tstamp) < TEST_ERROR_CONDITION)
      flash_led(PULSESENSOR_LED);
  }
  */
}


// blocking function
// Flash LED_BUILTIN||PULSESENSOR_LED to show things didn't work.
void flash_led(int led) {
  digitalWrite(led, LOW);
  delay(BUG_FLASH);
  digitalWrite(led, HIGH);
  delay(BUG_FLASH);
}

/* developing
void reset_vars() {
  // Initialize these vars to unlikely (impossible) values
  max_bpm = BPM_RESET;
  min_bpm = BPM_RESET + 255;
  avg_bpm = float(BPM_RESET);
  sd_bpm = -1.0;
  max_ibi = IBI_RESET;
  min_ibi = IBI_RESET + ?;
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
    limits_exceeded_counter[i].count = 0;

  // reset sending and receiving buffers
  for (int i=0; i<SHIPMENT_BUFFER_SIZE; i++)
    send_buff[i] = 0; // think it twice
  for (int i=0; i<RECEIVING_BUFFER_SIZE; i++)
    recv_buff[i] = 0; // think it twice

  bpm_ibi_sample_counter = 0;
  temp_sample_counter = 0;
}
*/

/*
  Attributes on flash:
    - data plan (max_messages)
    - sent messages counter (count_messages)
    - accumulated shipment delay (acc_shipment_delay)
    - last message timestamp (last_msg)
    - last EMERGENCY_MSG timestamp (emergency_msg_tstamp)
    - last LIMITS_MSG timestamp (limit_exceeded_msg_tstamp)
    - last ERROR_MSG timestamp (err_msg_tstamp)
*/

void update_flash(unsigned long last_msg, int max_messages) {
}

/*
int init_sigfox_module() {
  sigfox_err_tstamp = millis();
  while (!SigFox.begin()) { // Sigfox shield error
    while ((millis() - sigfox_err_tstamp) < TEST_ERROR_CONDITION)
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

byte send_msg() {
  byte attempts = 1;
  String msg_type = // cast(get first three bits from send_buff)
  unsigned long previous_shipment = last_msg;

  if !(init_sigfox_module())
    return 0;

  // compute measurements

  if (msg_type != LIMITS_MSG) {
    // check if any measurement has been exceeded
    for (int=0; i<6; i++)
      if (limits_exceeded_counter[i].count) {
        // limits_exceeded at some point but couldnt send report
        switch (msg_type) {
          case EMERGENCY_MSG:
            set_msg_type(EMERGENCY_LIMITS_MSG, first_shipment);
          case REPORT_MSG:
            if (failed_emergency_msg)
              set_msg_type(EMERGENCY_LIMITS_MSG, first_shipment);
            else
              set_msg_type(LIMITS_MSG, first_shipment);
       // case ERROR_MSG??
        }
        break;
      }
  }
  
  if (failed_emergency_msg) {
    switch (msg_type) {
      case LIMITS_MSG:
        set_msg_type(EMERGENCY_LIMITS_MSG, first_shipment);
      default // msg_type == EMERGENCY_MSG/REPORT_MSG/ERROR_MSG
        set_msg_type(EMERGENCY_MSG, first_shipment);
    }
  }

  // configure payload (based on msg_type) on send_buff
  // in case of LIMITS_MSG||EMERGENCY_LIMITS_MSG send also limits_exceeded_counter values
  // compress payload (based on msg_type?)

  while (1) {
    if (call to sigfox backend) {
      last_msg = millis();
      /* x, x+3-> x+3+12+9 problem. Developing
      if ((last_msg - previous_shipment) < SHIPMENT_INTERVAL) {
        set_shipment_timer(SHIPMENT_INTERVAL);
      }
      */
      if (failed_emergency_msg) {
        /*** 
         set here to 0 (not on button_pushed()) because
         a message != EMERGENCY_MSG may occur before
         a pending EMERGENCY_MSG would be triggered again
         ***/
        failed_emergency_msg = 0;
      }
      if (first_shipment) {
        // wait response (x time), get data
        if response
          first_shipment = 0;
      }
      break;
    }
    // Failed shipment
    if (++attempts > MAX_SHIPMENT_ATTEMPTS) {
      SigFox.end();
      return 0;
    }
    // delay next attempt (timer)?
  }

  // set timestamps (REPORT_MSG uses last_msg timestamp)
  switch (msg_type) {
    case EMERGENCY_LIMITS_MSG:
      emergency_msg_tstamp = last_msg;
      limit_exceeded_msg_tstamp = last_msg;
      break;
    case LIMITS_MSG:
      limit_exceeded_msg_tstamp = last_msg;
      break;
    case EMERGENCY_MSG:
      emergency_msg_tstamp = last_msg;
      break;
    case ERROR_MSG:
      err_msg_tstamp = last_msg;
      break;
  }

  count_messages++;
  update_flash(last_msg, max_messages);
  reset_vars();
  SigFox.end();

  return 1;
}

/*
void set_shipment_timer(unsigned long miliseconds) {
}

void handle_failed_shipment(byte msg_type, unsigned long tstamp) {
  set_shipment_timer(); // Retry automatically in X miliseconds -> based on msg_type
  // Samples lost?
}

void set_msg_type(String msg_type, byte first_shipment) {
  if (first_shipment)
    // set first three bits to msg_type + initial_msg on send_buff
  else
    // set first three bits to msg_type on send_buff
}

*/


// triggered once per minute (by timer?) to measure body temperature
void get_temperature() {
  float temperature = // Compute temperature on TEMPERATURE_PIN;
  temp_hist[temp_sample_counter] = temperature;
  temp_sample_counter++;

  if (check_upper_limit(temperature))
    limit_exceeded(4, millis());
  else
    if (check_lower_limit(temperature))
      limit_exceeded(5, millis());
}


/**
  Interrupt Service Routine button_pushed()
    -> triggered whenever the user pushes the emergency button
**/
/*
void button_pushed() {
  // noInterrupts();
  unsigned long tstamp = millis();

  // check if an EMERGENCY_MSG has been sent recently
  if ((emergency_msg_tstamp != 0) && 
      ((tstamp - emergency_msg_tstamp) < EMERGENCY_MSG_DELAY))
    return; // actually the same emergency

  if (count_messages == max_messages) {
    failed_emergency_msg = 1;
    handle_failed_shipment(EMERGENCY_MSG, tstamp);
    return;
  }

  set_msg_type(EMERGENCY_MSG, first_shipment);
  failed_emergency_msg = !(send_msg());
  if (failed_emergency_msg)
    handle_failed_shipment(EMERGENCY_MSG, tstamp);

//  if !(send_msg()) {
//    failed_emergency_msg = 1;
//    handle_failed_shipment(EMERGENCY_MSG, tstamp);
//  }

  // interrupts();
}


// triggered every SHIPMENT_INTERVAL miliseconds (by timer)
// to send biometric data to the Sigfox backend
void send_common_report() {
  unsigned long tstamp = millis();
  if (count_messages == max_messages) {
    handle_failed_shipment(REPORT_MSG, tstamp);
    return;
  }
  set_msg_type(REPORT_MSG, first_shipment);
  if !(send_msg())
    handle_failed_shipment(REPORT_MSG, tstamp);
}


void send_error_report() {
  unsigned long tstamp = millis();

  // check if an ERROR_MSG has been sent
  if ((err_msg_tstamp != 0) &&
     ((tstamp - err_msg_tstamp) < ERROR_MSG_DELAY))
      return;

  if (count_messages == max_messages) {
    handle_failed_shipment(ERROR_MSG, tstamp);
    return;
  }
  set_msg_type(ERROR_MSG, first_shipment);
  if !(send_msg())
    handle_failed_shipment(ERROR_MSG, tstamp);
}


void limit_exceeded(byte measure, unsigned long tstamp) {

  limits_exceeded_counter[measure].count++;

  // check if an EMERGENCY_MSG has been sent recently
  if ((emergency_msg_tstamp != 0) &&
     ((tstamp - emergency_msg_tstamp) < EMERGENCY_MSG_DELAY))
  {
    handle_failed_shipment(LIMITS_MSG, tstamp);
    return;
  }

  // check if a LIMITS_MSG has been sent recently
  if ((limit_exceeded_msg_tstamp != 0) &&
      ((tstamp - limit_exceeded_msg_tstamp) < LIMITS_MSG_DELAY))
  {
    handle_failed_shipment(LIMITS_MSG, tstamp);
    return;
  }

  if (count_messages == max_messages) {
    handle_failed_shipment(LIMITS_MSG, tstamp);
    return;
  }
  set_msg_type(LIMITS_MSG, first_shipment);
  if !(send_msg()) {
    handle_failed_shipment(LIMITS_MSG, tstamp);
    return;
  }
}
*/

/*
  Overloaded function series to check if any 
  limit has been exceeded
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
    // reduce sampling (32kb SRAM)
    bpm = bytecast(pulseSensor.getBeatsPerMinute());
    ibi = pulseSensor.getInterBeatIntervalMs();
    bpm_hist[bpm_ibi_sample_counter] = bpm;
    ibi_hist[bpm_ibi_sample_counter] = ibi;
    bpm_ibi_sample_counter++; // count bpm and ibi readings

    set_max_and_min(bpm, ibi);

    //check limits
    if (check_upper_limit(bpm))
      limit_exceeded(0, millis());
    else
      if (check_lower_limit(bpm))
        limit_exceeded(1, millis());

    if (check_upper_limit(ibi))
      limit_exceeded(2, millis());
    else
      if (check_lower_limit(ibi))
        limit_exceeded(3, millis());

      /*******
       Here is a good place to add code that could take up
       to a milisecond or so to run.
      *******/
  }
  /*
  if (millis() - last_msg >= SHIPMENT_INTERVAL)
    send_common_report();
  */
}
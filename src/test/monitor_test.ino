/*
   Every Sketch that uses the PulseSensor Playground must
   define USE_ARDUINO_INTERRUPTS before including PulseSensorPlayground.h.
   Here, #define USE_ARDUINO_INTERRUPTS false tells the library to
   not use interrupts to read data from the PulseSensor.

   If you want to use interrupts, simply change the line below
   to read:
     #define USE_ARDUINO_INTERRUPTS true

   Set US_PS_INTERRUPTS to false if either
   1) Your Arduino platform's interrupts aren't yet supported
   by PulseSensor Playground, or
   2) You don't wish to use interrupts because of the side effects.

   NOTE: if US_PS_INTERRUPTS is false, your Sketch must
   call pulse.sawNewSample() at least once every 2 milliseconds
   to accurately read the PulseSensor signal.
*/

#define USE_ARDUINO_INTERRUPTS false   // Set-up low-level interrupts for most acurate BPM math.
//#define US_PS_INTERRUPTS false
#include <PulseSensorPlayground.h>     // Includes the PulseSensorPlayground Library.   
#include <SigFox.h>

//  Variables
const int PulseWire = 0;       // PulseSensor PURPLE WIRE connected to ANALOG PIN 0
int Threshold = 535;           // Determine which Signal to "count as a beat" and which to ignore.                               
PulseSensorPlayground pulseSensor;  // Creates an instance of the PulseSensorPlayground object

int messages;
int iloop = 0;
int max_bpm_limit = 125;
int min_bpm_limit = 60;
//int max_ibi_limit = 125;
//int min_ibi_limit = 60;
int bpm_hist[200?];
int ibi_hist[200]?;


void setup() {

  Serial.begin(9600);          // For Serial Monitor
  while (!Serial) ;

  if (SigFox.begin())
    messages = 0;
  else {
    Serial.println("Shield error or not present!");
    return;
  }

  //send the module to standby until we need to send a message
  SigFox.end();

  // Configure the PulseSensor object, by assigning our variables to it. 
  pulseSensor.analogInput(PulseWire);   
  pulseSensor.blinkOnPulse(LED_BUILTIN);  //auto-magically blink Arduino's LED with heartbeat.
  pulseSensor.setThreshold(Threshold);

  // Now that everything is ready, start reading the PulseSensor signal.
  if (pulseSensor.begin())
    Serial.println("We created a pulseSensor Object !");
  else {
    /*
      PulseSensor initialization failed,
      likely because our Arduino platform interrupts
      aren't supported yet.

      If your Sketch hangs here, try changing USE_PS_INTERRUPT to false.
     */
    Serial.println("Problems to start reading PulseSensor");
    for(;;) {
     // Flash the led to show things didn't work.
      digitalWrite(LED_BUILTIN, LOW);
      delay(3000);
      digitalWrite(LED_BUILTIN, HIGH);
      delay(3000);
    }
  }
}

int send_alert_report() {
}

int send_common_report() {
}

/*
  Returns 0 for bpm and ibi values within the range,
  1 when limits have been exceeeded
*/
int limits_exceeded(int bpm, int ibi) {
  if (((bpm>max_bpm_limit) || (bpm<min_bpm_limit)) ||
      ((ibi>max_ibi_limit) || (ibi<min_ibi_limit)))
    return 1;
  return 0;
}

void loop() {
  /*
     See if a sample is ready from the PulseSensor.

     If USE_INTERRUPTS is true, the PulseSensor Playground
     will automatically read and process samples from
     the PulseSensor.

     If USE_INTERRUPTS is false, this call to sawNewSample()
     will, if enough time has passed, read and process a
     sample (analog voltage) from the PulseSensor.
  */

  if (pulseSensor.sawNewSample()) {
    last_bpm = pulseSensor.getBeatsPerMinute();
    last_ibi = pulseSensor.getInterBeatIntervalMs();
    bpm_hist[iloop] = last_bpm;
    ibi_hist[iloop] = last_ibi;
    
    // bpm or ibi limits exceeded
    if (limits_exceeded(last_bpm, last_ibi)) {
      send_alert_report();
    }


    //pulseSensor.outputBeat(); //IBI and BPM to Serial Monitor

    Serial.print("BPM:");
    Serial.print(bpm);
    Serial.print(", IBI:"); 
    Serial.println(ibi);
    //if (pulseSensor.sawStartOfBeat()) // Constantly test to see if "a beat happened". 
      //Serial.println("♥  A HeartBeat Happened ! ");

    /*******
     Here is a good place to add code that could take up
     to a millisecond or so to run.
     *******/

    iloop++; // count bpm and ibi readings
  }

  /******
    Don't add code here, because it could slow the sampling
    from the PulseSensor.
   ******/
}
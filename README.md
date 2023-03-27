
# Patient's heart rate and temperature monitoring system on ARDUINO MKRFOX1200

This project aims to be a monitoring system for aged people based on the ARDUINO MKRFOX1200 board and a couple of sensors that will monitor heart 
rate and temperature body measures. The board will send a set of metrics based on data recorded by these sensors throug Sigfox's network which is 
accesible through its library for this board and an already included data plan. Data will be gathered, buffered and processed on our Monitoring Service, which, in turn, will make them available to the medical team and related people through a web interface. Our Monitoring Service will implement some additional funciontalities like notifying an emergency condition to the predefined telephone numbers via Whatssap or SMS systems.


## Message types

There are several types of messages that our ArduinoMKRFOX1200 will send to the Monitoring Service:

- ERROR_MSG: Some error happened on any of the sensors.

- REPORT_MSG: Sent in normal conditions. That is no errors on the sensors, absence of limits exceeded, and the user did not pressed the alarm 
button.

- LIMITS_MSG: Sent whenever the device records a limit exceeded.

- REC_LIMITS_MSG: LIMITS_MSG recovery message.

- ALARM_MSG: The user pressed the alarm button on the device at some point on the last sampling interval.

- REC_ALARM_MSG: ALARM_MSG recovery message.

- ALARM_LIMITS_MSG: On last sampling interval, the user pressed the alarm button and some exceeded limit has been detected.

- REC_ALARM_LIMITS_MSG: ALARM_LIMITS_MSG recovery message.


## Payload format

Our ArduinoMKRFOX1200 patient monitoring program will deliver messages to the Sigfox backend following a specific format. Let's establish a terminology to make things easier:

- e: emergency bit (1 bit)
- r: emergency reason payload (1 bit)
- p: shipment policy (2 bits)
- m: message type (3 bits)
- RP: bpm ranges fields + payload variant (3 bytes + 9 control bits)
- ab: average bpm of the interval (1 byte)
- maxb: highest record of bpm variable on the interval (1 byte)
- minb: lowest record of bpm variable on the interval (1 byte)
- ai: average interbeat interval (ibi) of the (sampling) interval (2 bytes)
- maxi: highest record of interbeat interval (ibi) variable on the (sampling) interval (2 bytes)
- mini: lowest record of interbeat interval (ibi) variable on the (sampling) interval (2 bytes)
- t: temperature record of the interval (4 bytes)
- x: elapsed milliseconds since the recovery message was stored (4 bytes)

* Types of Payload:

Payload format variant 0:  e:r:p:m:RP:ab:maxb:minb:t
Payload format variant 1:  e:r:p:m:RP:ab:maxb:minb:maxi:mini
Payload format variant 2:  e:r:p:m:RP:ab:ai:t
Payload format variant 3:  e:r:p:m:RP:ab:ai:maxi:mini
Payload format variant 4:  e:r:p:m:RP:ab(-1):t (PulseSensor Error, On ERROR_MSG)
Payload format variant 5:  e:r:p:m:RP:ab:maxb:minb:maxi:mini (Temperature Sensor Error, on ERROR_MSG)
Payload format variant 6:  e:r:p:m:RP:ab:ai:maxi:mini (Temperature Sensor Error, on ERROR_MSG)
Payload format variant 7:  (original_payload-(last 4 bytes)):x


**Notes on control fields**

- emergency bit (e field) set to 0 indicates there's no ongoing emergency happening at the device's end, therefore patient has not pressed the emergency button so far or at least, since last emergency. Bit set to 1 indicates the opposite.

- Emergency reason payload (r field) set to 1 indicates that this payload is the original reason from the current emergency, which was triggered at the detection of any of the triggering emergency conditions.

- Shipment policy bits (p field):

* 00: No policies active. Regular shipment rate
* 01: Emergency shipment policy is active
* 10: Recovery shipment policy is active

- Message type (m field): Indicates the message type of the payload.

- Bpm ranges fields + Payload format variant (RP field): Looking to the first control bit from every value (percentage) from this field, we compound a three-bit indicator that lets the service know what kind of payload will have to process. The whole RP field looks like this, having:

xxx: range id bits
i: n-bit of the three-bit payload format indicator
r: positive integer numerator of the fraction r/100 (7 bits)

RP field: xxx:i:r:xxx:i:r:xxx:i:r


**Given that a percentage won't reach any value higher than 100, we use the the most significant bit (i) from every r value on the RP field to compound a three-bit indicator of the payload format variant**.


## Features


## Connecting sensors to ArduinoMKRFOX1200


##  Uploading Sketch

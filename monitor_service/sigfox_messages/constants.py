# Message types 
ALARM_MSG = 0
LIMITS_MSG = 1
ALARM_LIMITS_MSG = 2
ERROR_MSG = 3
REC_ALARM_MSG = 4
REC_LIMITS_MSG = 5
REC_ALARM_LIMITS_MSG = 6
REPORT_MSG = 7

# Shipment policies
REGULAR_SHIP_POLICY = 0
EMERGENCY_SHIP_POLICY = 1
RECOVERY_SHIP_POLICY = 2
DEVICE_BOOTED = 3

# Number of days to keep patients data,
# after which all records will be erased from Database.
KEEP_RECORDS = 10

# After every shipment, we let the PulseSensorPlayground Library to
# process patient's heart rate data for this amount of seconds before
# requesting patient's data again, therefore delaying sample gathering
# for such amount of time.
MIN_PROCESSING_TIME = 5

# Time in seconds that the device takes to complete the Sigfox's Library
# 'send()' function on the device for uplink/downlink messagess, which
# substract computing time to process samples on every interval. Whenever
# a downlink message is sent, usually on the first message of the device
# after booting, an uplink is also sent, so both delays take place in such
# case (UPLINK_DELAY + DOWNLINK_DELAY).
UPLINK_DELAY = 8
DOWNLINK_DELAY = 30

# Quantity to be added (substracted) to the configured upper (lower)
# bpm limit to calculate its emergency limit on the device.
# So for instance, if we have a lower limit of 70 bpm, and this value
# is set to 10, the lower bpm limit configured to trigger emergency on
# the device will be set to 60. This setup is thought to save space on
# downlink payloads, instead of shipping the whole value (5 bits vs 1 byte).
# Hence, maximum value to be set for them is 31.
HIGHER_BPM_ELIMIT_SUM = 15
LOWER_BPM_ELIMIT_SUM = 10

# 22'40" (higher recovery sequence delay plus failed shipment (1 min) plus 
# delivery delay (40 seconds) from Sigfox Backend)
MAX_TIME_DELAY = 1360

# Regular interval duration (REGULAR_SHIP_POLICY shipment rate)
REGULAR_INTERVAL_DURATION = 630 # in seconds

# Mimimum time to regard a new emergency message as another emergency (in minutes)
NEW_EMERG_DELAY = 45

# Mimimum time to resend a SMS notification (in minutes)
SMS_DELAY = 15

# Specify the minimum number of chats which must acknowledge the emergency
# situation (issue '/stop' command) before stopping the notification
# process for those who haven't noticed yet. Set it to 0 to keep notification
# process active until the user acknowledges the emergency.
STOP_ON_NCHATS_AWARENESS = 2

## TELEGRAM API LIMITS ##
# Keep our Bot and Notification processes responsive by keeping
# our shipping rates above the maximum allowed by the Telegram Service.
# To not overload Telegram servers and keep our Bot and Notification
# processes responsive, a seconds delay must be introduced between calls to Bot's
# shipping functions like send_message() and reply_to(). Keep it as close
# to the maximum shipping rates allowed as possible (about 30 messages per second
# on different chats and 1 on a single chat according to Telegram API),
# for the sake of scalability and responsiveness. If these vars are set over the 
# rate limits, eventually it'll result in error codes from Telegram library

CHAT_MESSAGE_DELAY = 1.5  # Maximum of 1 message per second for a single chat
MESSAGE_DELAY = 0.04  # Maximum of 30 messages per second on different chats

# Specify the notification period in seconds for chats
NOTIFICATION_PERIOD = 30

# Specify the wait in seconds for a notifier process to leave notification loop
NOTIFIER_WAIT = 30

# FOR BEST RESULTS ON EMERGENCY ACKNOWLEDGMENT, BEST KEEP 'MAX_NOTIFICATION_TIME'
# TO A VALUE LOWER THAN 'NEW_EMERG_DELAY'. NOT MANDATORY.
# Specify the maximum notification time, in minutes, while the notification process
# is active without "emergency acknowledgement" for both Telegram and SMS contact
# systems.
MAX_NOTIFICATION_TIME = 30

# Default coordinates to "Unknown"
DEFAULT_COORDINATE = "Unknown"

# Device statuses
FUNCTIONAL_DEV_STATUS = "Functional"
PULSESENSOR_ERR_DEV_STATUS = "PulseSensor error"
MAX30205_ERR_DEV_STATUS = "MAX30205 error"

# Service url, only used for displaying the service url on Telegram notifications.
SERVICE_URL = "http://127.0.0.1:8000/sigfox_messages"

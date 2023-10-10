
# Estimation of number of samples for each interval
REGULAR_SHIP_UPDATE_SAMPLES = 315000

# 22'40" (higher recovery sequence delay plus failed shipment (1 min) plus 
# delivery delay (40 seconds) from Sigfox Backend)
MAX_TIME_DELAY = 1360

# Mimimum time to regard a new emergency message as another emergency (in seconds)
NEW_EMERG_DELAY = 2700 # 45 minutes

# Mimimum time to resend a SMS notification (in minutes)
SMS_DELAY = 20

# Introduce seconds delay between calls to send_message()
MESSAGE_DELAY = 2

# Specify the wait in seconds for a notifier process to leave loop
NOTIFIER_WAIT = 30

# Specify the notification period in seconds for chats
NOTIFICATION_PERIOD = 25

# Msg types 
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

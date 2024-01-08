from sigfox_messages import models, constants
from asgiref.sync import sync_to_async, async_to_sync
from datetime import datetime, timedelta
from functools import partial
from django.utils import timezone
from channels.db import database_sync_to_async
import asyncio, struct, time

message_delta = timedelta(microseconds=int(constants.MESSAGE_DELAY*10**6))
chat_message_delta = timedelta(microseconds=int(constants.CHAT_MESSAGE_DELAY*10**6))

ALARM_PUSHED = "alarm_pushed"
EMERG_SPOTTED = "emergency_spotted"

SMS_ALERT_MESSAGE = "--MONITORING SYSTEM ALERT--\n\nHello, we notify "
SMS_ALERT_MESSAGE += "you for a recently arisen emergency in some of the "
SMS_ALERT_MESSAGE += "patients you're currently monitoring. Check out your "
SMS_ALERT_MESSAGE += "Telegram's chat for more info.\n\n--MONITORING SYSTEM ALERT--\n\n"

STOPPED_MESSAGE = "---ALERT SYSTEM STOPPED---\n\n"
STOPPED_MESSAGE += "If you want to get the latest patient biometrics, visit "
STOPPED_MESSAGE += constants.SERVICE_URL + "\n\n---ALERT SYSTEM STOPPED---"


async def send_sms_alert(contact, message):

  from sigfox_messages.bot import vonage_client

  if (vonage_client == None):
    print("Vonage client object equals to None. Skipping SMS shipping")
    return

  # print(f"Sending SMS to number {contact.phone_number} at: {datetime.now()}", flush=True)
  loop = asyncio.get_running_loop()
  d = {"from": "VONAGE API", "to": contact.phone_number, "text": message}
  await loop.run_in_executor(None, partial(vonage_client.sms.send_message, d))
  print(f"SMS message sent to number {contact.phone_number} at: {datetime.now()}", flush=True)
  # print(f"Account balance: {vonage_client.account.get_balance()}", flush=True)
  print()


async def check_sleep(timestamp, message_delay=constants.MESSAGE_DELAY):

  if (message_delay == constants.MESSAGE_DELAY):
    mdelta = message_delta
  else: # constants.CHAT_MESSAGE_DELAY
    mdelta = chat_message_delta

  delta = datetime.now() - timestamp
  if (delta.total_seconds() < message_delay):
    # print(f"{delta.total_seconds()} (delta.total_seconds) < {message_delay} (message_delay)", flush=True)
    # Sleep until shipping is possible
    delta = (timestamp + mdelta) - datetime.now()
    # print(f"sleeping {round(delta.total_seconds(), 3)} seconds to send..", flush=True)
    await asyncio.sleep(round(delta.total_seconds(), 3))


async def get_chat_message_locks(echat_id, chat_timestamp_notifier_alock=None):

  from sigfox_messages.bot import chat_timestamp_lock, last_chat_message_dlock
  from sigfox_messages.bot import manager, last_chat_message, chat_message_alock_store

  if (chat_timestamp_notifier_alock != None):
    # manage access to "chat_timestamp_lock" among Notifier tasks
    await chat_timestamp_notifier_alock.acquire()
  else:
    from sigfox_messages.bot import chat_timestamp_bot_alock
    # manage access to "chat_timestamp_lock" among different Bot tasks
    await chat_timestamp_bot_alock.acquire()

  ## Critical lock for performance. Accessed by Bot and all Notifier Processes
  chat_timestamp_lock.acquire()
  if (echat_id not in last_chat_message_dlock):
    # Creating an asyncio.Lock() from calling task may result on error when
    # trying to pickle a weakref (as those created by asyncio.Lock())
    last_chat_message_dlock[echat_id] = manager.Lock()
    last_chat_message[echat_id] = datetime.now() - chat_message_delta

  chat_message_lock = last_chat_message_dlock[echat_id]
  chat_timestamp_lock.release() # Release it quickly, so it becomes available for other chats

  if (chat_timestamp_notifier_alock != None):
    chat_timestamp_notifier_alock.release()
    chat_message_alock = None
  else:
    chat_message_alock = chat_message_alock_store.get_lock(echat_id)
    chat_timestamp_bot_alock.release()

  return chat_message_alock, chat_message_lock


# Used by Bot tasks to reply to user messages
async def wrap_bot_reply(message, **kwargs):

  from sigfox_messages.bot import last_message_alock

  chat_message_alock, chat_message_lock = await get_chat_message_locks(str(message.chat.id))
  await send(last_message_alock, chat_message_lock,
             chat_message_alock=chat_message_alock,
             message=message, **kwargs)


# Used by notifier processes
async def wrap_send(last_message_alock, **kwargs):

  # As there's only one notifier task active per chat,
  # the 'chat_message_alock' is not necessary to get access to
  # 'chat_message_lock' lock
  _, chat_message_lock = await get_chat_message_locks(kwargs["echat_id"],
                                                      chat_timestamp_notifier_alock=\
                                                      kwargs["chat_timestamp_notifier_alock"])
  await send(last_message_alock, chat_message_lock, **kwargs)


async def send(last_message_alock, chat_message_lock, chat_message_alock=None, **kwargs):

  from sigfox_messages.bot import bot

  reply_markup = 0
  if ("message" in kwargs): # Bot reply
    reply = 1
    echat_id = str(kwargs["message"].chat.id)
  else:
    reply = 0
    echat_id = kwargs["echat_id"]

  if ("text" in kwargs):
    mtype = "text message"
    if reply:
      send_func = bot.reply_to
      args = (kwargs["message"], kwargs["text"])
      if (("reply_markup" in kwargs) and
          (kwargs["reply_markup"] != None)):
        reply_markup = 1
    else:
      send_func = bot.send_message
      args = (echat_id, kwargs["text"])
  elif (("latitude" in kwargs) and ("longitude" in kwargs)):
    mtype = "location"
    send_func = bot.send_location
    args = (echat_id, kwargs["latitude"], kwargs["longitude"])
  else:
    print("Wrong parameters passed to send function", flush=True)
    return

  # **Only one task from a process must access a manager.Lock() at a time**
  # Avoid locking a manager.Lock() from several tasks of the same process.
  # asyncio.Lock() locks are used to regulate access to it.

  # Locking order: (Inverse order for releasing)
  # chat_message_alock->chat_message_lock->last_message_alock->last_message_lock

  from sigfox_messages.bot import last_message_lock, last_message, last_chat_message

  if (chat_message_alock != None): # Bot reply task
    await chat_message_alock.acquire()

  chat_message_lock.acquire()
  # Assure there's at least 'constants.CHAT_MESSAGE_DELAY' seconds difference
  # between calls to bot.reply_to(), bot.send_message() or bot.send_location()
  # on the same chat
  await check_sleep(last_chat_message[echat_id], constants.CHAT_MESSAGE_DELAY)

  await last_message_alock.acquire()
  last_message_lock.acquire()
  # Assure there's at least 'constants.MESSAGE_DELAY' seconds difference
  # between calls to bot.reply_to(), bot.send_message() or bot.send_location()
  # Keep the locks acquired
  await check_sleep(last_message.value, constants.MESSAGE_DELAY)

  # print(f"sending {mtype} to '{echat_id}' at: {datetime.now()}", flush=True)
  if reply_markup:
    await send_func(*args, reply_markup=kwargs["reply_markup"])
  else:
    await send_func(*args)

  timestamp = datetime.now()
  last_message.value = timestamp
  last_message_lock.release()
  last_message_alock.release()
  last_chat_message[echat_id] = timestamp
  chat_message_lock.release()
  if (chat_message_alock != None): # Bot reply task
    chat_message_alock.release()

  print(f"{mtype} sent to {echat_id} at {timestamp}", flush=True)


def my_get_attr(obj, attr):
  return getattr(obj, attr)

def my_set_attr(obj, attr, attr_value):
  return setattr(obj, attr, attr_value)

async_my_get_attr = sync_to_async(my_get_attr, thread_sensitive=True)
async_my_set_attr = sync_to_async(my_set_attr, thread_sensitive=True)

async_Patient_Contact_filter = sync_to_async(models.Patient_Contact.objects.filter,
                                             thread_sensitive=True)

async_Device_History_filter = sync_to_async(models.Device_History.objects.filter,
                                            thread_sensitive=True)
async_Emergency_Payload_filter = sync_to_async(models.Emergency_Payload.objects.filter,
                                               thread_sensitive=True)
async_Emergency_Biometrics_filter = sync_to_async(models.Emergency_Biometrics.objects.filter,
                                                  thread_sensitive=True)

def Patient_Contact_exclude(patient, contact):
  return models.Patient_Contact.objects.filter(patient=patient).exclude(contact=contact)

async_Patient_Contact_exclude = sync_to_async(Patient_Contact_exclude, thread_sensitive=True)


@database_sync_to_async
def async_save(obj):
  obj.save()


def retrieve_field(bin_data, index, length):

  field = ""
  top = index + length
  for ibit in bin_data[index:top]:
    field += ibit

  return (int(field, 2))


def retrieve_temp(bin_data, index, length):

  temp_bin = ""
  top = index + length
  for ibit in bin_data[index:top]:
    temp_bin += ibit

  return struct.unpack('>f', struct.pack(">i", int(temp_bin, 2)))[0]


def get_attr_name(range_id):
  if range_id == 0:
    return "lower_range"
  elif range_id == 1:
    return "second_range"
  elif range_id == 2:
    return "third_range"
  else:
    return "higher_range"


def get_ranges(lower_bpm_limit, higher_bpm_limit, **kwargs):

  if ("emergency" in kwargs):
    lower_rvalue = kwargs["emergency"].lower_range
    second_rvalue = kwargs["emergency"].second_range
    third_rvalue =  kwargs["emergency"].third_range
    higher_rvalue =  kwargs["emergency"].higher_range
  elif ("epayload" in kwargs):
    lower_rvalue = kwargs["epayload"].lower_range
    second_rvalue = kwargs["epayload"].second_range
    third_rvalue =  kwargs["epayload"].third_range
    higher_rvalue =  kwargs["epayload"].higher_range
  elif ("bio_24" in kwargs):
    lower_rvalue = kwargs["bio_24"].lower_range
    second_rvalue = kwargs["bio_24"].second_range
    third_rvalue =  kwargs["bio_24"].third_range
    higher_rvalue =  kwargs["bio_24"].higher_range
  elif ("bio" in kwargs):
    lower_rvalue = kwargs["bio"].lower_range
    second_rvalue = kwargs["bio"].second_range
    third_rvalue =  kwargs["bio"].third_range
    higher_rvalue =  kwargs["bio"].higher_range
  else:
    print("Missing arguments on get_ranges()")
    return []

  aux = (higher_bpm_limit - lower_bpm_limit) // 2 # Floor division
  range_top = lower_bpm_limit + aux
  if (((higher_bpm_limit - lower_bpm_limit) % 2) == 0): # Even number
    range_top-=1

  lower_range = "<" + str(lower_bpm_limit)
  second_range = "[" + str(lower_bpm_limit) + ", " + str(range_top) + "]"
  third_range = "[" + str(range_top+1) + ", " + str(higher_bpm_limit) + "]"
  higher_range = ">" + str(higher_bpm_limit)

  return [(lower_range, lower_rvalue),
          (second_range, second_rvalue),
          (third_range, third_rvalue),
          (higher_range, higher_rvalue)]


def check_emergency_deactivation(emergency, datetime_obj):

  minutes = int((get_sec_diff(datetime_obj, emergency.spawn_timestamp)) // 60) # Convert it to minutes
  if (minutes >= constants.NEW_EMERG_DELAY):
    print("Deactivating emergency", end=' ', flush=True)
    print(emergency, flush=True)
    emergency.active = False  # Deactivate emergency
    emergency.termination_timestamp = models.Device_History.objects.filter(dev_conf=emergency.patient.dev_conf).\
                                      latest("date").last_msg_time
    emergency.save()

  return emergency


# Erase all Biometrics older than 'days' days
def check_biometrics_deletion(days=constants.KEEP_RECORDS):

  datetime_obj = timezone.make_aware(datetime.now())
  key_date = datetime_obj.date() - timedelta(days=days)

  # Erase Biometrics records
  qs = models.Biometrics.objects.filter(date__lt=key_date)
  if (qs.exists()):
    qs.delete()

  for patient in models.Patient.objects.all():
    try:
      bio_24 = models.Biometrics_24.objects.get(patient=patient)
      dev_hist = models.Device_History.objects.filter(dev_conf=patient.dev_conf).latest("date")
    except models.Biometrics_24.DoesNotExist:
      continue
    except models.Device_History.DoesNotExist:
      dev_hist = None

    if (dev_hist == None): # bio_24 not empty
      bio_24.delete()
    else:
      # Erase bio_24 instance if it was recorded more than 'days' days ago
      delta = (datetime_obj.date() - dev_hist.date)
      if (delta.days > days):
        bio_24.delete()
        dev_hist.delete() # Erase also associated entry in Device_History


# Erase all Emergencies older than 'days' days and
# epayloads/attention requests linked to them
def check_emergency_deletion(days=constants.KEEP_RECORDS):

  datetime_obj = timezone.make_aware(datetime.now())
  key_datetime_obj = datetime_obj - timedelta(days=days)

  for emergency in models.Emergency_Biometrics.objects.filter(spawn_timestamp__lt=key_datetime_obj):
    qs = models.Emergency_Payload.objects.filter(emergency=emergency)
    if (qs.exists()):
      qs.delete()
    try:
      att_req = models.Attention_request.objects.get(emergency=emergency)
      att_req.delete()
    except models.Attention_request.DoesNotExist:
      pass
    emergency.delete()

  # Erase also old 'manual' attention requests
  qs = models.Attention_request.objects.filter(request_timestamp__lt=key_datetime_obj)
  if (qs.exists()):
    qs.delete()


# Erase all Device_History older than 'days' days
def check_device_history_deletion(days=constants.KEEP_RECORDS):

  datetime_obj = timezone.make_aware(datetime.now())
  key_date = datetime_obj.date() - timedelta(days=days)

  qs = models.Device_History.objects.filter(date__lt=key_date)
  if (qs.exists()):
    qs.delete()


# Erases all records older than 'days' days
def check_old_records(days=constants.KEEP_RECORDS):
  # This function is meant to be used by a separate process.
  # It gets executed once a day, performs its necessary checkings
  # over Database models, and goes to sleep again, for 24 hours,
  # until next execution. It runs over and over and over concurrently
  # with the Monitor Service and the Telegram Bot.
  while 1:
    print("Performing the checking over old database records..", flush=True)
    check_biometrics_deletion(days=days)
    check_device_history_deletion(days=days)
    check_emergency_deletion(days=days)
    print("Checking done. Sleeping 24 hours until next checking..", flush=True)
    time.sleep(24*60*60)


def get_interval(delta):

  time = ""
  seconds = (delta.seconds % 60)
  mins = int(delta.seconds // 60)
  if (mins >= 60):
    hours = int(mins//60)
    mins %= 60
    if (hours < 10):
      time += "0"
    time += str(hours) + ":"
  else:
    time += "00:"
  
  if (mins < 10):
    time += "0"
  time += str(mins) + ":"

  if (seconds < 10):
    time += "0"
  time += str(seconds)

  return time


# Substract one day to the given date
def delta(date):

  d = timedelta(1)
  date = date - d

  return date


def get_sec_diff(datetime_obj, datetime_obj2):

  dobj = datetime_obj - datetime_obj2

  return dobj.seconds


def get_bio(dev_hist, bio_24=None, ebio=None):

  if (bio_24 != None):
    bio = bio_24
    msg_count = dev_hist.uplink_count
  elif (ebio != None):
    bio = ebio
    msg_count = ebio.emsg_count
  else: # Failed update
    bio = None
    msg_count = None

  return bio, msg_count


def update_ranges(dev_hist, attr, attr_value, bio_24=None, ebio=None):

  bio, msg_count = get_bio(dev_hist, bio_24, ebio)

  if (bio == None): # Failed update
    return

  # print(f"(uplink) attr = {attr}")
  # bpm ranges and related fields are set directly
  range_sum_field = attr + "_sum"
  # print(f"(uplink) range_sum_field = {range_sum_field}")
  if ((msg_count == 1) or (getattr(bio, range_sum_field) == "")):
    setattr(bio, range_sum_field, str(float(attr_value)))
    setattr(bio, attr, str(float(attr_value)))
  else:
    setattr(bio, range_sum_field, str(float(attr_value) + float(getattr(bio, range_sum_field))))
    setattr(bio, attr, str(round(float(getattr(bio, range_sum_field))/float(msg_count), 2)))


def update_temp(dev_hist, attr_value, bio_24=None, ebio=None):

  bio, msg_count = get_bio(dev_hist, bio_24, ebio)

  if (bio == None): # Failed update
    return

  # Temperature related attributes are set directly
  bio.last_temp = str(round(attr_value, 3))

  # On the next if, pick up any temperature field to check out that these fields have already
  # been initialized (msg_count > 1, but an ERROR_MSG message due to Temperature sensor error
  # could have been sent prior to this one, so temperature fields may equal to "")
  if ((msg_count > 1) and (bio.sum_temp != "")):
    bio.sum_temp = str(round((float(bio.sum_temp) + attr_value), 3))
    if (attr_value < float(bio.min_temp)):
      bio.min_temp = bio.last_temp
    elif (attr_value > float(bio.max_temp)):
      bio.max_temp = bio.last_temp
    bio.avg_temp = str(round((float(bio.sum_temp)/msg_count), 3))
  else:
    bio.sum_temp = bio.last_temp
    bio.min_temp = bio.last_temp
    bio.max_temp = bio.last_temp
    bio.avg_temp = bio.last_temp


def update_bpm_ibi(dev_hist, attr, attr_value, bio_24=None, ebio=None, datetime_obj=None, shipment_policy=0):

  bio, msg_count = get_bio(dev_hist, bio_24, ebio)

  if (bio == None): # Failed update
    return

  if (datetime_obj != None): # on average updates
    date = datetime_obj.date()

  if ((msg_count > 1) and (getattr(bio, attr) != "")):
    if ((attr == "max_bpm") and (attr_value > bio.max_bpm)):
      bio.max_bpm = attr_value
    elif ((attr == "min_bpm") and (attr_value < bio.min_bpm)):
      bio.min_bpm = attr_value
    elif ((attr == "max_ibi") and (attr_value > bio.max_ibi)):
      bio.max_ibi = attr_value
    elif ((attr == "min_ibi") and (attr_value < bio.min_ibi)):
      bio.min_ibi = attr_value
    elif ((attr == "avg_bpm") or (attr == "avg_ibi")):

      if ((ebio != None) and (dev_hist.uplink_count==1)):
        # (ebio.emsg_count > 1), but it's the first message of the day
        date = delta(date) # Purpose is getting the time of yesterday's last message
        try:
          dev_hist = models.Device_History.objects.get(dev_conf=dev_hist.dev_conf, date=date)
        except models.Device_History.DoesNotExist:
          print("There's no device history object created yesterday")
          return # This should never happen. Catch exception if it does, to continue.

      seconds = get_sec_diff(datetime_obj, dev_hist.last_msg_time)
      if (seconds <= constants.MAX_TIME_DELAY):
        sum_field = "sum_" + attr[4:]
        time_field = attr[4:] + "_time"
        # print(f"(uplink) attr = {attr}")
        # print(f"(uplink) attr[4:] = {attr[4:]}")
        # print(f"(uplink) time_field (attr[4:] + '_time') = {time_field}")
        partial_sum = attr_value * (seconds * 500) # 500 samples per second
        # print(f"(uplink) attr_value = {attr_value}")
        # print(f"(uplink) partial_sum = {partial_sum}")
        setattr(bio, sum_field, getattr(bio, sum_field) + partial_sum)
        # print(f"(uplink) bio.sum_field = {getattr(bio, sum_field)}")
        setattr(bio, time_field, getattr(bio, time_field) + seconds)
        # print(f"(uplink) bio.time_field = {getattr(bio, time_field)}")
        setattr(bio, attr, round(getattr(bio, sum_field)/(getattr(bio, time_field) * 500)))
      else:
        pass # Lack of continuity upon message delivery. Leave avg_bpm/avg_ibi without updating
  else:
    # First value of the day/emergency or both
    setattr(bio, attr, attr_value)

    if ((attr == "avg_bpm") or (attr == "avg_ibi")):
      sum_field = "sum_" + attr[4:]
      time_field = attr[4:] + "_time"

      # Inititialize sum and time fields
      setattr(bio, sum_field, 0)
      setattr(bio, time_field, 0)

      if (bio_24 != None):
        if (shipment_policy == constants.REGULAR_SHIP_POLICY):
          setattr(bio, sum_field, attr_value * 630 * 500)
          setattr(bio, time_field, 630) # regular shipment interval in seconds

        elif (shipment_policy == constants.RECOVERY_SHIP_POLICY):
          # Former day passed in the midst of a RECOVERY_SHIP_POLICY
          # We know this because any device's first message is always either within
          # an EMERGENCY_SHIP_POLICY or a REGULAR_SHIP_POLICY.
          date = delta(date)
          try:
            dev_hist = models.Device_History.objects.get(dev_conf=dev_hist.dev_conf, date=date)
            seconds = get_sec_diff(datetime_obj, dev_hist.last_msg_time)
            if (seconds <= constants.MAX_TIME_DELAY):
              setattr(bio, sum_field, attr_value * seconds * 500)
              setattr(bio, time_field, seconds)
            else:
              pass # Lack of continuity upon message delivery. Leave avg_bpm/avg_ibi without updating
          except models.Device_History.DoesNotExist:
            pass
        else: # EMERGENCY_SHIP_POLICY
          # We don't have a way to determine how much time the device has been gathering samples since it booted up.
          # We know 'x' falls within 0<x<=10'30" range, but we don't know it accurately, so we start measuring
          # device's computing time from the second message onwards to update the average(s).
          pass

      elif ((ebio != None) and (dev_hist.uplink_count > 1)): # (ebio.emsg_count == 1)
        seconds = get_sec_diff(datetime_obj, dev_hist.last_msg_time)
        if (seconds <= constants.MAX_TIME_DELAY):
          setattr(bio, sum_field, (attr_value * seconds * 500))
          setattr(bio, time_field, seconds)
        else:
          pass # Lack of continuity upon message delivery. Leave fields without updating
      else:
        # We don't have a way to determine how much time the device has been gathering samples since it booted up.
        # We know 'x' falls within 0<x<=10'30" range, but we don't know it accurately, so we start measuring
        # device's computing time from the second message onwards to update the average(s).
        pass


async def send_dev_data(**kwargs):

  from sigfox_messages.bot import bot

  contact = kwargs["contact"]
  patient = kwargs["patient"]

  loc_avail = 0
  latitude = constants.DEFAULT_COORDINATE
  longitude = constants.DEFAULT_COORDINATE
  dev_conf = await async_my_get_attr(patient, "dev_conf")
  dev_hist_qs = await async_Device_History_filter(dev_conf=dev_conf)
  dev_hist = None
  exists = await dev_hist_qs.aexists()
  if exists:
    try:
      dev_hist = await dev_hist_qs.alatest("date")
      latitude = dev_hist.last_known_latitude
      longitude = dev_hist.last_known_longitude
    except models.Device_History.DoesNotExist:
      pass

  title_msg = "---DEVICE DATA FROM PATIENT '" + patient.name.upper()
  title_msg += " " + patient.surname.upper() + "'---"

  if (dev_hist != None):
    message = title_msg + "\nLast message sent: "
    message += str(dev_hist.last_msg_time) + "\nLast known location: "

    if (latitude != constants.DEFAULT_COORDINATE and
        longitude != constants.DEFAULT_COORDINATE):
      loc_avail = 1
      message += "(lat:" + latitude + ", long:" + longitude + ")"
    else:
      message += "Not available"
  else:
    message = title_msg + "\nThere are no records available from '"
    message +=  patient.name + " " + patient.surname + "' device."
    message += " Unable to get device location."

  if ("bot_message" in kwargs): # Regular '/locate' command interaction
    await wrap_bot_reply(kwargs["bot_message"], text=message)
    if loc_avail:
      # Last location available
      await wrap_bot_reply(kwargs["bot_message"], latitude=latitude, longitude=longitude)
  elif ("last_message_alock" in kwargs):
    # Ongoing notifier process trying to send data
    await wrap_send(kwargs["last_message_alock"], echat_id=contact.echat_id, text=message,
                    chat_timestamp_notifier_alock=kwargs["chat_timestamp_notifier_alock"])
    if loc_avail:
      await wrap_send(kwargs["last_message_alock"], echat_id=contact.echat_id,
                      latitude=latitude, longitude=longitude,
                      chat_timestamp_notifier_alock=kwargs["chat_timestamp_notifier_alock"])


async def set_notifications_done(contact, pcontact_qs, save_chat=False,
                                 set_contact=False, set_comm=False, stop_set=False):

  if save_chat:
    from sigfox_messages.bot import SPAWN_CONFIG
    contact.echat_state = SPAWN_CONFIG
    await async_save(contact)

  async for pcontact in pcontact_qs:
    if set_contact:
      await async_my_set_attr(pcontact, "contact", contact)
    if stop_set:
      await async_my_set_attr(pcontact, "stop_set", True)
      await async_my_set_attr(pcontact, "comm_status", "Done")
    elif set_comm:
      await async_my_set_attr(pcontact, "comm_status", "Done")
    await async_save(pcontact)


async def check_stop(pcontact_qs, pcontact_dict):

  stop_on_chats = False
  stopped = 0
  exists = await pcontact_qs.aexists()
  if exists:
    pcontact = pcontact_qs[0] # Get any pcontact from the QuerySet
    contact = await async_my_get_attr(pcontact, "contact")
  else:
    print("check_stop(): Patient_Contact QuerySet argument was empty", flush=True)
    return stop_on_chats, stopped

  try: # Query database for contact status update
    contact = await models.Contact.objects.aget(echat_id=contact.echat_id)
  except models.Contact.DoesNotExist:
    print("Error retrieving contact id", flush=True)
    return stop_on_chats, stopped

  from sigfox_messages.bot import ALERTING

  if (contact.echat_state != ALERTING):
    stopped = 1
    await set_notifications_done(contact, pcontact_qs, set_contact=True, stop_set=True)
    return stop_on_chats, stopped

  stopped = 1
  async for pcontact in pcontact_qs:
    while 1:
      try: # Query database for attention_request status update
        att_req = await models.Attention_request.objects.aget(emergency=pcontact_dict[pcontact][0])
        if (att_req.status == "Attended"):
          await async_my_set_attr(pcontact, "comm_status", "Done")
          await async_save(pcontact)
        else:
          stopped = 0 # Not all emergencies in 'pcontact_dict' have been attended
        break
      except models.Attention_request.DoesNotExist:
        print("Attention_request does not exist", flush=True)
        await asyncio.sleep(2) # Wait for it to be created on database

  if stopped: # All emergencies have been attended, stop alerting
    await set_notifications_done(contact, pcontact_qs, save_chat=True, set_contact=True)
  elif (constants.STOP_ON_NCHATS_AWARENESS > 0):
    # Check out whether all "pending" emergencies have already been noticed in
    # related chats (at least on constants.STOP_ON_NCHATS_AWARENESS chats)
    # through the issuing of '/stop' command. In that case, stop notifications
    # also for this chat (release notification system's workload)
    stopped = 1
    pcontact_qs = await async_Patient_Contact_filter(contact=contact, comm_status="Pending")
    async for pcontact in pcontact_qs:
      patient = await async_my_get_attr(pcontact, "patient")
      qs = await async_Patient_Contact_exclude(patient, contact)
      if ((await qs.aexists()) and
         ((await qs.acount()) >= constants.STOP_ON_NCHATS_AWARENESS)):
        stop_set = 0
        async for pcont in qs:
          if (((await async_my_get_attr(pcont, "comm_status")) == "Done") and
              (await async_my_get_attr(pcont, "stop_set"))):
            stop_set += 1
            if (stop_set == constants.STOP_ON_NCHATS_AWARENESS):
              break
        if (stop_set < constants.STOP_ON_NCHATS_AWARENESS):
          stopped = 0
          break
      else:
        stopped = 0
        break

    if stopped:
      # constants.STOP_ON_NCHATS_AWARENESS condition was met.
      # Stop notifications for this chat (contact)
      stop_on_chats = True
      await set_notifications_done(contact, pcontact_qs, save_chat=True,
                                   set_contact=True, set_comm=True)

  return stop_on_chats, stopped


async def get_emergency_message(pcontact_dict):

  message = "---AUTOMATED EMERGENCY NOTIFICATION---\n\nHello, we send you this message because"

  if (len(pcontact_dict) == 1):
    pcontact, value = next(iter(pcontact_dict.items()))
    patient = await async_my_get_attr(pcontact, "patient")
    message_type = value[1]
    if (message_type == EMERG_SPOTTED):
      message += " monitor device, from patient '" + patient.name.upper() + " "
      message += patient.surname.upper() + "', spotted an emergency condition (BPM LIMIT EXCEEDED)."
    else: # ALARM_PUSHED message
      message += " patient '" + patient.name.upper() + " " + patient.surname.upper() + "' recently"
      message += " pushed the alarm button on his monitor device (ALARM_MSG)."
  else:
    message += " several emergencies were detected across some of your patients:\n\n"
    for pcontact, value in pcontact_dict.items():
      patient = await async_my_get_attr(pcontact, "patient")
      message_type = value[1]
      message += "'" + patient.name.upper() + " " + patient.surname.upper() + "': "
      if (message_type == EMERG_SPOTTED):
        message += "emergency condition spotted (BPM LIMIT EXCEEDED)"
      else: # ALARM_PUSHED message
        message += "pushed device's alarm button (ALARM_MSG)"
      message += '\n'

  message += "\nPlease issue '/stop' command to let us know that you are aware of the situation."
  message += "\n\n---AUTOMATED EMERGENCY NOTIFICATION---"

  return message


async def wait_event(event, timeout=None):

  loop = asyncio.get_running_loop()
  if (timeout != None):
    was_set = await loop.run_in_executor(None, partial(event.wait, timeout=timeout))
  else:
    was_set = await loop.run_in_executor(None, event.wait)

  return was_set


async def release_notifier(**kwargs):

  exit_message = kwargs["exit_message"]
  pcontact_list = kwargs["pcontact_list"]
  pcontact_dict = kwargs["pcontact_dict"]
  applicant_event = kwargs["applicant_event"]
  notifier_event = kwargs["notifier_event"]
  comm_status = kwargs["comm_status"]
  notifier = kwargs["notifier"]
  notifier_dict = kwargs["notifier_dict"]
  last_message_alock = kwargs["last_message_alock"]
  chat_timestamp_notifier_alock = kwargs["chat_timestamp_notifier_alock"]

  for pcontact in pcontact_list:
    contact = await async_my_get_attr(pcontact, "contact")
    patient = await async_my_get_attr(pcontact, "patient")
    await send_dev_data(last_message_alock=last_message_alock,
                        contact=contact, patient=patient,
                        chat_timestamp_notifier_alock=chat_timestamp_notifier_alock)

  # Notify also about "Attended/Not Attended" status of related emergencies for every patient
  message = ""
  for pcontact in pcontact_list:
    contact = await async_my_get_attr(pcontact, "contact")
    patient = await async_my_get_attr(pcontact, "patient")
    try: # Query database for attention_request status update
      att_req = await models.Attention_request.objects.aget(emergency=pcontact_dict[pcontact][0])
      available = 1
      if (att_req.status == "Attended"):
        att_value = "' has been marked as 'Attended' on the Monitor System"
      else:
        att_value = "' is still 'Unattended'"
    except models.Attention_request.DoesNotExist:
      available = 0

    if available:
      attended_msg = "Last emergency from patient '" + patient.name.upper()
      attended_msg += " " + patient.surname.upper() + att_value
    else:
      attended_msg = "Attention request status for patient '" + patient.name.upper()
      attended_msg += " " + patient.surname.upper() + "' is not available"

    message += attended_msg + '\n' # Join all request status

  # message = message[:(len(message)-1)] # Strip last '\n' character
  await wrap_send(last_message_alock, echat_id=contact.echat_id, text=message+'\n'+exit_message,
                  chat_timestamp_notifier_alock=chat_timestamp_notifier_alock)
  notifier.acquire()
  notifier_dict[contact.echat_id] = False
  notifier.release()
  comm_status.release()
  notifier_event.set()
  print("Waiting for applicant_event to be set to leave notification loop ", end='', flush=True)
  print(f"for chat {contact.echat_id}", flush=True)
  # was_set = applicant_event.wait(timeout=30)
  was_set = await wait_event(applicant_event, timeout=constants.NOTIFIER_WAIT)
  if was_set:
    print(f"applicant_event was set for chat = {contact.echat_id} ", flush=True)
  else:
    print(f"applicant_event timed out for chat = {contact.echat_id} ", flush=True)
  # applicant_event.clear() # Placed here this call generates errors, avoid it


async def notify_contact(**kwargs):

  from sigfox_messages.bot import ALERTING, wait_emergency

  pcontact = kwargs["pcontact"]
  comm_status = kwargs["comm_status"]
  notifier = kwargs["notifier"]
  notifier_dict = kwargs["notifier_dict"]
  notifier_event = kwargs["notifier_event"]
  applicant_event = kwargs["applicant_event"]
  stop_event = kwargs["stop_event"]
  last_message_alock = kwargs["last_message_alock"]
  chat_timestamp_notifier_alock = kwargs["chat_timestamp_notifier_alock"]

  contact = await async_my_get_attr(pcontact, "contact")
  patient = await async_my_get_attr(pcontact, "patient")

  # If we are within this function, it means we've already acquired 'notifier lock'
  # related to this chat
  notifier_dict[contact.echat_id] = True
  notifier.release()
  notifier_event.set()

  # Notify a possible notifier for this chat that we've already used/released the locks,
  # so it's enabled to exit. We do this in order to avoid likely exceptions
  # (i.e. BrokenPipeError) due to processes having used the same lock but ended their execution.
  # Keep them alive until we release the lock by setting up the 'applicant' event when we are done
  # using it.
  applicant_event.set() # Set it up for ongoing notifier about to exit
  stop_event.clear()

  # Update pcontact/contact fields
  contact.echat_state = ALERTING
  await async_save(contact)
  await async_my_set_attr(pcontact, "contact", contact)
  await async_save(pcontact)

  # Create Patient_Contact QuerySet with that pcontact object
  pcontact_qs = await async_Patient_Contact_filter(patient=patient, contact=contact)
  pcontact_list = [await pcontact_qs.afirst()]
  origin_pcontact_dict = {}
  origin = 1 # Original while iteration (First call to notify_contact())
  while 1:
    pcontact_dict = {}
    async for pcontact in pcontact_qs:
      patient = await async_my_get_attr(pcontact, "patient")
      emerg_event = wait_emergency[patient.dni]
      while 1:
        # Wait until a new record for patient's latest emergency is saved on Database
        await wait_event(emerg_event)
        emerg_qs = await async_Emergency_Biometrics_filter(patient=patient)
        try:
          # Get the latest emergency record
          emergency = await emerg_qs.alatest("spawn_timestamp")
          pcontact_dict[pcontact] = [emergency, ""]
          break
        except models.Emergency_Biometrics.DoesNotExist: # Should never happen
          print(f"emerg_event was set for patient {patient.name} {patient.surname}",
                end='', flush=True)
          print(" but there are no emergencies on DB", flush=True)
          await asyncio.sleep(2) # Do not continue, retry in 2 seconds

      # Set default message
      pcontact_dict[pcontact][1] = EMERG_SPOTTED
      while 1:
        epayload_qs = await async_Emergency_Payload_filter(emergency=emergency)
        exists = await epayload_qs.aexists()
        if exists:
          async for epayload in epayload_qs:
            if (epayload.ereason_payload):
              if (epayload.msg_type == "ALARM_LIMITS_MSG" or
                  epayload.msg_type == "ALARM_MSG"):
                pcontact_dict[pcontact][1] = ALARM_PUSHED
              else:
                pcontact_dict[pcontact][1] = EMERG_SPOTTED
              break
            elif (epayload.msg_type == "ALARM_LIMITS_MSG" or
                  epayload.msg_type == "ALARM_MSG"):
              pcontact_dict[pcontact][1] = ALARM_PUSHED
          break
        else:
          print("Waiting for payload to be saved on DB", flush=True)
          await asyncio.sleep(2) # Wait for it to be created on database

      # Track all emergencies since notifier started
      origin_pcontact_dict[pcontact] = pcontact_dict[pcontact]
      if (pcontact not in pcontact_list):
        pcontact_list.append(pcontact)

    # Send 4 initial notifications
    if origin:
      origin = 0
      message = await get_emergency_message(pcontact_dict)
      await wrap_send(last_message_alock, echat_id=contact.echat_id, text=message,
                      chat_timestamp_notifier_alock=chat_timestamp_notifier_alock)
      origin_time = datetime.now() # Save first notification timestamp
      for e in range(1, 4):
        stop_set = await wait_event(stop_event, timeout=5)
        if stop_set:
          break
        await wrap_send(last_message_alock, echat_id=contact.echat_id, text=message,
                        chat_timestamp_notifier_alock=chat_timestamp_notifier_alock)

      if ((not stop_set) and (contact.sms_alerts)):
        stop_set = await wait_event(stop_event, timeout=10)
        if (not stop_set):
          await send_sms_alert(contact, SMS_ALERT_MESSAGE)
          sms_timestamp = datetime.now()

    # Wait 'constants.NOTIFICATION_PERIOD' seconds to send next notification
    stop_set = await wait_event(stop_event, timeout=constants.NOTIFICATION_PERIOD)

    # Clear 'notifier_event' to tell all applicants for this chat to remain active until 
    # this notifier releases 'comm_status' lock
    notifier_event.clear()
    comm_status.acquire()  # We may change all 'pcontact_qs' status to "Done" within check_stop()
    stop_on_chats, stop = await check_stop(pcontact_qs, pcontact_dict)
    comm_status.release()
    notifier_event.set()

    if not stop:
      message = await get_emergency_message(pcontact_dict)
      if (contact.sms_alerts):
        sms_delay = int((get_sec_diff(datetime.now(), sms_timestamp)) // 60) # Convert it to minutes
        if (sms_delay >= constants.SMS_DELAY):
          await asyncio.sleep(10)
          await send_sms_alert(contact, SMS_ALERT_MESSAGE)
          sms_timestamp = datetime.now()
          await asyncio.sleep(10)
      await wrap_send(last_message_alock, echat_id=contact.echat_id, text=message,
                      chat_timestamp_notifier_alock=chat_timestamp_notifier_alock)

    notifier_event.clear()
    # Acquire comm_status lock to check about any pcontact.comm_status == 'pending' presence
    comm_status.acquire()
    pcontact_qs = await async_Patient_Contact_filter(contact=contact, comm_status="Pending")
    notify = await pcontact_qs.aexists()
    if (notify == False): # stop == True
      # Stop notifying ('/stop' command issued, all emergencies were marked as 'Attended' or
      # constants.STOP_ON_NCHATS_AWARENESS condition was met)
      message = ""
      if stop_on_chats:
        message = "*Other users have already noticed the situation. Stopping notification process*\n\n"
      await release_notifier(exit_message=message+STOPPED_MESSAGE,
                             pcontact_list=pcontact_list,
                             pcontact_dict=origin_pcontact_dict,
                             applicant_event=applicant_event,
                             notifier_event=notifier_event,
                             comm_status=comm_status,
                             notifier=notifier,
                             notifier_dict=notifier_dict,
                             last_message_alock=last_message_alock,
                             chat_timestamp_notifier_alock=chat_timestamp_notifier_alock)
      return # Leave notification loop
    elif stop: # notify == True
      # Some stop condition was satisfied, but a new emergency arouse after calling check_stop()
      # Continue to notify unless '/stop' command was issued
      if stop_set:
        # Set notifications done for the new 'pcontact_qs' QuerySet
        await set_notifications_done(contact, pcontact_qs, set_contact=True, stop_set=True)
        message = "**New emergencies have been detected for the following patients**:\n\n"
        async for pcontact in pcontact_qs:
          patient = await async_my_get_attr(pcontact, "patient")
          message += "Patient " + patient.name.upper() + " "
          message += patient.surname.upper() + "\n"
        message += "\n**New emergencies detected**\n\n"
        await release_notifier(exit_message=message+STOPPED_MESSAGE,
                               pcontact_list=pcontact_list,
                               pcontact_dict=origin_pcontact_dict,
                               applicant_event=applicant_event,
                               notifier_event=notifier_event,
                               comm_status=comm_status,
                               notifier=notifier,
                               notifier_dict=notifier_dict,
                               last_message_alock=last_message_alock,
                               chat_timestamp_notifier_alock=chat_timestamp_notifier_alock)
        return # Leave notification loop
      else:
        # Since we're going to continue notifying, we need to restore chat's state to 'ALERTING'
        # (which was set to 'SPAWN_CONFIG' within check_stop())
        contact.echat_state = ALERTING
        await async_save(contact)
    else: # notify == True
      delta = datetime.now() - origin_time
      elapsed_minutes = int(delta.total_seconds() // 60)
      if (elapsed_minutes >= constants.MAX_NOTIFICATION_TIME):
        await set_notifications_done(contact, pcontact_qs, save_chat=True,
                                     set_contact=True, set_comm=True)
        message = "(Maximum notification time for this phone number consumed.\n"
        message += "Exiting notification process)\n\n"
        await release_notifier(exit_message=message+STOPPED_MESSAGE,
                               pcontact_list=pcontact_list,
                               pcontact_dict=origin_pcontact_dict,
                               applicant_event=applicant_event,
                               notifier_event=notifier_event,
                               comm_status=comm_status,
                               notifier=notifier,
                               notifier_dict=notifier_dict,
                               last_message_alock=last_message_alock,
                               chat_timestamp_notifier_alock=chat_timestamp_notifier_alock)
        return # Leave notification loop

    # No stop condition was satisfied
    comm_status.release()
    notifier_event.set()


def notifier(patient):

  from sigfox_messages.bot import contacts_lock, event_dict_lock, event_dict
  from sigfox_messages.bot import comm_statuses_lock, comm_status_dict_lock
  from sigfox_messages.bot import notifiers_lock, notifier_dict_lock, notifier_dict

  busy_chats = {}
  async def notify():

    tasks_created = 0
    last_message_alock = asyncio.Lock() # Shared among all tasks of the process
    # Hold this asyncio.Lock() to manage access to "chat_timestamp_lock" 
    # among different Notifier tasks
    chat_timestamp_notifier_alock = asyncio.Lock()
    contacts_lock.acquire()
    pcontact_qs = await async_Patient_Contact_filter(patient=patient)
    async for pcontact in pcontact_qs:
      contact = await async_my_get_attr(pcontact, "contact")
      event_dict_lock.acquire()
      (notifier_event, applicant_event, stop_event) = event_dict[contact.echat_id]
      event_dict_lock.release()
      comm_statuses_lock.acquire()
      comm_status = comm_status_dict_lock[contact.echat_id]
      comm_statuses_lock.release()
      applicant_event.clear()
      comm_status.acquire() # Acquire lock to set pcontact fields
      await async_my_set_attr(pcontact, "comm_status", "Pending")
      await async_my_set_attr(pcontact, "stop_set", False)
      await async_save(pcontact)
      comm_status.release()
      notifiers_lock.acquire()
      notifier = notifier_dict_lock[contact.echat_id]
      notifiers_lock.release()
      notifier.acquire() # Acquire notifier lock to access 'notifier' value
      notifier_value = notifier_dict[contact.echat_id]
      if (notifier_value == True):
        print(f"There's an ongoing notification task for chat {contact.echat_id}", flush=True)
        notifier.release()
        # Take note of the chat that has an ongoing notifier process
        busy_chats[contact.echat_id] = (notifier_event, applicant_event)
        continue

      print(f"Getting in notify_contact() for chat {contact.echat_id}", flush=True)
      asyncio.create_task(notify_contact(pcontact=pcontact,
                                         notifier_event=notifier_event,
                                         applicant_event=applicant_event,
                                         comm_status=comm_status,
                                         notifier=notifier,
                                         notifier_dict=notifier_dict,
                                         stop_event=stop_event,
                                         last_message_alock=last_message_alock,
                                         chat_timestamp_notifier_alock=chat_timestamp_notifier_alock))
      tasks_created = 1

    contacts_lock.release()
    if tasks_created:
      tasks = asyncio.all_tasks()
      tasks.remove(asyncio.current_task())
      await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)

  asyncio.run(notify())

  for echat_id, (notifier_event, applicant_event) in busy_chats.items():
    notifiers_lock.acquire()
    if (echat_id in notifier_dict_lock):
      notifier = notifier_dict_lock[echat_id]
      notifiers_lock.release()
    else:
      # Contact has been removed from Database
      notifiers_lock.release()
      continue
    notifier.acquire() # Acquire notifier lock to access chat's 'notifier' value
    notifier_value = notifier_dict[echat_id]
    if (notifier_value == True):
      # Wait to exit until ongoing notifier from that chat enable us to do it
      notifier.release()
      print(f"Waiting for notifier_event from chat {echat_id} to be set to terminate", flush=True)
      # Single-threaded process checking out other notifier's state to leave gracefully.
      # No need to do the async wait with "await wait_event(notifier_event)"
      notifier_event.wait()
      print(f"chat's {echat_id} notifier_event set", flush=True)
    else:
      notifier.release()

    # Discarded, as the waiting side (applicant_event.wait() needs the process to be alive)
    # We'll use a timeout where an applicant_event.wait() call is made'
    # applicant_event.set() # Set it up to enable notifier's exit (Deprecated)

  print("Bye bye, says notifier", flush=True)


def check_empty_params(dictionary):
  err = 0
  output = ""
  for param in dictionary:
    if (dictionary[param] == ""):
      err = 1
      output = "You must provide all requested parameters"
      break
  return err, output

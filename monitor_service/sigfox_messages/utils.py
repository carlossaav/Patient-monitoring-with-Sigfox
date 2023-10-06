from sigfox_messages import models, constants
from asgiref.sync import sync_to_async, async_to_sync
import asyncio, struct, datetime

ALARM_PUSHED = "alarm_pushed"
EMERG_SPOTTED = "emergency_spotted"

SMS_ALERT_MESSAGE = "--MONITORING SYSTEM ALERT--\n\nHello, we notify "
SMS_ALERT_MESSAGE += "you for a recently arisen emergency in some of the "
SMS_ALERT_MESSAGE += "patients you're currently monitoring. Check out your "
SMS_ALERT_MESSAGE += "Telegram's chat for more info.\n\n--MONITORING SYSTEM ALERT--\n\n"


def send_sms_alert(contact, message):

  from sigfox_messages.bot import vonage_client

  if (vonage_client == None):
    print("Vonage client object equals to None. Skipping SMS shipping")
    return

  print(f"Account balance: {vonage_client.account.get_balance()}")
  print(f"Sending SMS to number {contact.phone_number}")
  vonage_client.sms.send_message({"from": "VONAGE API",
                                  "to": contact.phone_number,
                                  "text": message})
  print(f"Message sent. Account balance now: {vonage_client.account.get_balance()}")


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


# Substract one day to the given date
def delta(date):

  d = datetime.timedelta(1)
  date = date - d

  return date


def get_sec_diff(datetime_obj, datetime_obj2):

  dobj = datetime_obj - datetime_obj2

  return dobj.seconds


def get_bio(dev_hist, bio_24=None, ebio=None):

  if (bio_24 != None):
    bio = bio_24
    msg_count = int(dev_hist.uplink_count)
  elif (ebio != None):
    bio = ebio
    msg_count = int(ebio.emsg_count)
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
    if ((attr == "max_bpm") and (attr_value > int(bio.max_bpm))):
      bio.max_bpm = str(attr_value)
    elif ((attr == "min_bpm") and (attr_value < int(bio.min_bpm))):
      bio.min_bpm = str(attr_value)
    elif ((attr == "max_ibi") and (attr_value > int(bio.max_ibi))):
      bio.max_ibi = str(attr_value)
    elif ((attr == "min_ibi") and (attr_value < int(bio.min_ibi))):
      bio.min_ibi = str(attr_value)
    elif ((attr == "avg_bpm") or (attr == "avg_ibi")):

      if ((ebio != None) and (int(dev_hist.uplink_count)==1)):
        # (ebio.emsg_count > 1), but it's the first message of the day
        date = delta(date) # Purpose is getting the time of yesterday's last message
        try:
          dev_hist = models.Device_History.objects.get(dev_conf=dev_hist.dev_conf, date=date)
        except models.Device_History.DoesNotExist:
          print("There's no device history object created yesterday")
          return # This should never happen. Catch exception if it does, to continue.

      seconds = get_sec_diff(datetime_obj, dev_hist.last_msg_time)
      # print(f"(uplink) seconds = {seconds}")
      if (seconds <= constants.MAX_TIME_DELAY):
        sum_field = "sum_" + attr[4:]
        time_field = attr[4:] + "_time"
        # print(f"(uplink) attr = {attr}")
        # print(f"(uplink) attr[4:] = {attr[4:]}")
        # print(f"(uplink) time_field (attr[4:] + '_time') = {time_field}")
        partial_sum = attr_value * (seconds * 500) # 500 samples per second
        # print(f"(uplink) attr_value = {attr_value}")
        # print(f"(uplink) partial_sum = {partial_sum}")
        setattr(bio, sum_field, str(int(getattr(bio, sum_field)) + partial_sum))
        # print(f"(uplink) bio.sum_field = {int(getattr(bio, sum_field))}")
        setattr(bio, time_field, str(int(getattr(bio, time_field)) + seconds))
        # print(f"(uplink) bio.time_field = {int(getattr(bio, time_field))}")
        setattr(bio, attr, str(round(int(getattr(bio, sum_field))/(int(getattr(bio, time_field)) * 500))))
      else:
        pass # Lack of continuity upon message delivery. Leave avg_bpm/avg_ibi without updating
  else:
    # First value of the day/emergency or both
    setattr(bio, attr, attr_value)

    if ((attr == "avg_bpm") or (attr == "avg_ibi")):
      sum_field = "sum_" + attr[4:]
      time_field = attr[4:] + "_time"

      # Inititialize sum and time fields
      setattr(bio, sum_field, str(0))
      setattr(bio, time_field, str(0))

      if (bio_24 != None):
        if (shipment_policy == constants.REGULAR_SHIP_POLICY):
          setattr(bio, sum_field, str(attr_value * 630 * 500))
          setattr(bio, time_field, str(630)) # regular shipment interval in seconds

        elif (shipment_policy == constants.RECOVERY_SHIP_POLICY):
          # Former day passed in the midst of a RECOVERY_SHIP_POLICY
          # We know this because any device's first message is always either within
          # an EMERGENCY_SHIP_POLICY or a REGULAR_SHIP_POLICY.
          date = delta(date)
          try:
            dev_hist = models.Device_History.objects.get(dev_conf=dev_hist.dev_conf, date=date)
            seconds = get_sec_diff(datetime_obj, dev_hist.last_msg_time)
            if (seconds <= constants.MAX_TIME_DELAY):
              setattr(bio, sum_field, str(attr_value * seconds * 500))
              setattr(bio, time_field, str(seconds))
            else:
              pass # Lack of continuity upon message delivery. Leave avg_bpm/avg_ibi without updating
          except models.Device_History.DoesNotExist:
            pass
        else: # EMERGENCY_SHIP_POLICY
          # We don't have a way to determine how much time the device has been gathering samples since it booted up.
          # We know 'x' falls within 0<x<=10'30", range, but we don't know it accurately, so we start measuring
          # device's computing time from the second message onwards to update the average(s).
          pass

      elif ((ebio != None) and (int(dev_hist.uplink_count) > 1)): # (ebio.emsg_count == 1)
        seconds = get_sec_diff(datetime_obj, dev_hist.last_msg_time)
        if (seconds <= constants.MAX_TIME_DELAY):
          setattr(bio, sum_field, (attr_value * seconds * 500))
          setattr(bio, time_field, seconds)
        else:
          pass # Lack of continuity upon message delivery. Leave fields without updating
      else:
        # We don't have a way to determine how much time the device has been gathering samples since it booted up.
        # We know 'x' falls within 0<x<=10'30", range, but we don't know it accurately, so we start measuring
        # device's computing time from the second message onwards to update the average(s).
        pass


async def send_dev_data(contact, patient):

  from sigfox_messages.bot import send_message, send_location
  
  latitude = ""
  longitude = ""
  loc_avail = 0
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

    if (latitude != "" and longitude != ""):
      loc_avail = 1
      message += "(lat:" + latitude + ", long:" + longitude + ")"
    else:
      message += "Not available"
  else:
    message = title_msg + "\nThere are no records available from '"
    message +=  patient.name + " " + patient.surname + "' device."
    message += " Unable to get device location."

  await send_message(contact.echat_id, message)
  if loc_avail: # Last location available
    await asyncio.sleep(2)
    await send_location(contact.echat_id, latitude, longitude)


async def check_stop(**kwargs):

  pcontact_qs = kwargs["pcontact_qs"]
  pcontact_dict = kwargs["pcontact_dict"]
  comm_status = kwargs["comm_status"]
  notifier_event = kwargs["notifier_event"]

  stopped = 0
  exists = await pcontact_qs.aexists()
  if exists:
    pcontact = pcontact_qs[0] # Get any pcontact from the QuerySet
    contact = await async_my_get_attr(pcontact, "contact")
  else:
    print("check_stop(): Patient_Contact QuerySet argument was empty", flush=True)
    return stopped

  try: # Query database for contact status update
    contact = await models.Contact.objects.aget(echat_id=contact.echat_id)
  except models.Contact.DoesNotExist:
    print("Error retrieving contact id", flush=True)
    return stopped
  
  if (contact.echat_state != "ALERTING"):
    stopped = 1
    notifier_event.clear()
    comm_status.acquire()
    async for pcontact in pcontact_qs:
      await async_my_set_attr(pcontact, "contact", contact)
      await async_my_set_attr(pcontact, "comm_status", "Done")
      await pcontact.asave()
    comm_status.release()
    notifier_event.set()
    return stopped

  stopped = 1
  async for pcontact in pcontact_qs:
    while 1:
      try: # Query database for attention_request status update
        att_req = await models.Attention_request.objects.aget(emergency=pcontact_dict[pcontact][0])
        if (att_req.status == "Attended"):
          notifier_event.clear()
          comm_status.acquire()
          await async_my_set_attr(pcontact, "comm_status", "Done")
          await pcontact.asave()
          comm_status.release()
          notifier_event.set()
        else:
          stopped = 0 # Not all emergencies have been attended
        break
      except models.Attention_request.DoesNotExist:
        print("Attention_request does not exist", flush=True)
        await asyncio.sleep(5) # Wait for it to be created on database

  if stopped: # All emergencies have been attended, stop alerting
    from sigfox_messages.bot import SPAWN_CONFIG
    contact.echat_state = SPAWN_CONFIG
    await contact.asave()
    async for pcontact in pcontact_qs:
      await async_my_set_attr(pcontact, "contact", contact)
      await pcontact.asave()

  return stopped


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
    message += " several emergencies were detected in some of your patients:\n\n"
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


async def release_notifier(**kwargs):

  from sigfox_messages.bot import send_message

  exit_message = kwargs["exit_message"]
  pcontact_list = kwargs["pcontact_list"]
  pcontact_dict = kwargs["pcontact_dict"]
  applicant_event = kwargs["applicant_event"]
  comm_status = kwargs["comm_status"]
  notifier = kwargs["notifier"]
  notifier_dict = kwargs["notifier_dict"]

  for pcontact in pcontact_list:
    contact = await async_my_get_attr(pcontact, "contact")
    patient = await async_my_get_attr(pcontact, "patient")
    await send_dev_data(contact, patient)
    await asyncio.sleep(2)

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

  message = message[:(len(message)-1)] # Strip last '\n' character
  await send_message(contact.echat_id, message)
  # Try to distribute message shipments to Telegram to avoid reaching the limits
  await asyncio.sleep(2)
  await send_message(contact.echat_id, exit_message)
  notifier.acquire()
  notifier_dict[contact.echat_id] = "Off"
  notifier.release()
  comm_status.release()
  print("Waiting for applicant_event to be set to leave notification loop ", end='', flush=True)
  print(f"for chat {contact.echat_id}", flush=True)
  was_set = applicant_event.wait(timeout=30)
  if was_set:
    print(f"applicant_event was set for chat = {contact.echat_id} ", flush=True)
  else:
    print(f"applicant_event timed out for chat = {contact.echat_id} ", flush=True)
  # applicant_event.clear() # Placed here this call generates errors, avoid it



async def notify_contact(**kwargs):

  from sigfox_messages.bot import send_message, wait_emergency, STOPPED_MESSAGE

  pcontact = kwargs["pcontact"]
  comm_status = kwargs["comm_status"]
  notifier = kwargs["notifier"]
  notifier_dict = kwargs["notifier_dict"]
  notifier_event = kwargs["notifier_event"]
  applicant_event = kwargs["applicant_event"]
  stop_event = kwargs["stop_event"]

  contact = await async_my_get_attr(pcontact, "contact")
  patient = await async_my_get_attr(pcontact, "patient")

  # If we are within this function, it means we've already acquired 'notifier lock' related to this chat
  notifier_dict[contact.echat_id] = "Notifying"
  notifier.release()
  notifier_event.set()

  # Notify a possible notifier for this chat that we've already used/released the locks,
  # so it's enabled to exit. We do this in order to avoid likely exceptions (i.e. BrokenPipeError)
  # due to processes having used the same lock but ended their execution. Keep them alive
  # until we release the lock by setting up the 'applicant' event when we are done using it.
  applicant_event.set() # Set it up for ongoing notifier about to exit
  stop_event.clear()

  # Update pcontact/contact fields
  contact.echat_state = "ALERTING"
  await contact.asave()
  await async_my_set_attr(pcontact, "contact", contact)
  await pcontact.asave()

  # Create Patient_Contact QuerySet with that pcontact object
  pcontact_qs = await async_Patient_Contact_filter(patient=patient, contact=contact)
  pcontact_list = [await pcontact_qs.afirst()]
  origin_pcontact_dict = {}
  origin = 1 # Original while iteration (First call to notify_contact())
  notify = True
  while notify:
    pcontact_dict = {}
    async for pcontact in pcontact_qs:
      patient = await async_my_get_attr(pcontact, "patient")
      emerg_event = wait_emergency[patient.dni]
      while 1:
        # Wait until a new record for patient's latest emergency is saved on Database
        emerg_event.wait()
        emerg_qs = await async_Emergency_Biometrics_filter(patient=patient)
        try:
          # Get the latest emergency record
          emergency = await emerg_qs.alatest("emerg_timestamp")
          pcontact_dict[pcontact] = [emergency, ""]
          break
        except models.Emergency_Biometrics.DoesNotExist: # Should never happen
          print(f"emerg_event was set for patient {patient.name} {patient.surname}",
                end='', flush=True)
          print(" but there are no emergencies on DB", flush=True)
          await asyncio.sleep(5) # Do not continue, retry in 5 seconds

      # Get saved emergency, set default message
      emerg = pcontact_dict[pcontact][0]
      pcontact_dict[pcontact][1] = EMERG_SPOTTED
      while 1:
        epayload_qs = await async_Emergency_Payload_filter(emergency=emerg)
        exists = await epayload_qs.aexists()
        if exists:
          async for epayload in epayload_qs:
            if (epayload.ereason_payload == "Yes"):
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
          asyncio.sleep(5) # Wait for it to be created on database

      # Track all emergencies since notifier started
      origin_pcontact_dict[pcontact] = pcontact_dict[pcontact]
      if (pcontact not in pcontact_list):
        pcontact_list.append(pcontact)

    # Send 4 initial notifications
    if origin:
      origin = 0
      message = await get_emergency_message(pcontact_dict)
      for e in range(1, 5):
        await send_message(contact.echat_id, message)
        stop_set = stop_event.wait(timeout=5)
        if stop_set:
          break

      if ((stop_set == False) and (contact.sms_alerts == "Yes")):
        await asyncio.sleep(10)
        send_sms_alert(contact, SMS_ALERT_MESSAGE)
        sms_timestamp = datetime.datetime.now()

    # Wait 20 seconds to send next notification
    stop_event.wait(timeout=25)
    stop = await check_stop(pcontact_qs=pcontact_qs,
                            pcontact_dict=pcontact_dict,
                            comm_status=comm_status,
                            notifier_event=notifier_event)
    if not stop:
      message = await get_emergency_message(pcontact_dict)
      await send_message(contact.echat_id, message)
      if (contact.sms_alerts == "Yes"):
        sms_delay = (get_sec_diff(datetime.datetime.now(), sms_timestamp)) // 60 # Convert it to minutes
        if (sms_delay >= constants.SMS_DELAY):
          await asyncio.sleep(10)
          send_sms_alert(contact, SMS_ALERT_MESSAGE)
          sms_timestamp = datetime.datetime.now()
          await asyncio.sleep(10)

    # Clear event to tell all applicants for this chat to remain active unti notifier releases the locks
    notifier_event.clear()
    # Acquire comm_status lock to check about any pcontact.comm_status == 'pending' presence
    comm_status.acquire()
    pcontact_qs = await async_Patient_Contact_filter(contact=contact, comm_status="Pending")
    notify = await pcontact_qs.aexists()
    if (notify == False):
      # Stop notifying ('/stop' issued or all emergencies were marked as 'Attended')
      await release_notifier(exit_message=STOPPED_MESSAGE,
                             pcontact_list=pcontact_list,
                             pcontact_dict=origin_pcontact_dict,
                             applicant_event=applicant_event,
                             comm_status=comm_status,
                             notifier=notifier,
                             notifier_dict=notifier_dict)
    elif stop: # notify == True
      message = "**New emergencies have been detected for the following patients**:\n\n"
      async for pcontact in pcontact_qs:
        patient = await async_my_get_attr(pcontact, "patient")
        message += "Patient '" + patient.name.upper() + " "
        message += patient.surname.upper() + "'\n"
      message += "\n**New emergencies detected**\n\n"
      await release_notifier(exit_message=message+STOPPED_MESSAGE,
                             pcontact_list=pcontact_list,
                             pcontact_dict=origin_pcontact_dict,
                             applicant_event=applicant_event,
                             comm_status=comm_status,
                             notifier=notifier,
                             notifier_dict=notifier_dict)
      return # Leave notification loop
    else: # notify == True
      # One or more pcontact.comm_status are still in "Pending" state and user haven't noticed yet
      comm_status.release()
      notifier_event.set()


def notifier(patient):

  from sigfox_messages.bot import contact_lock, event_dict_lock, event_dict
  from sigfox_messages.bot import comm_statuses_lock, comm_status_dict_lock
  from sigfox_messages.bot import notifiers_lock, notifier_dict_lock, notifier_dict

  busy_chats = {}
  async def notify():

    tasks_created = 0
    contact_lock.acquire()
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
      comm_status.acquire() # Acquire lock to set 'pcontact pending' value
      await async_my_set_attr(pcontact, "comm_status", "Pending")
      await pcontact.asave()
      comm_status.release()
      
      notifiers_lock.acquire()
      notifier = notifier_dict_lock[contact.echat_id]
      notifiers_lock.release()
      notifier.acquire() # Acquire notifier lock to access 'notifier' value
      notifier_value = notifier_dict[contact.echat_id]
      if (notifier_value == "Notifying"):
        print(f"There's an ongoing notification task for chat {contact.echat_id}", flush=True)
        # print("There's an ongoing notification task for this chat.", flush=True)
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
                                         stop_event=stop_event))
      tasks_created = 1

    contact_lock.release()
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
    if (notifier_value == "Notifying"):
      # Wait to exit until ongoing notifier from that chat enable us to do it
      notifier.release()
      print(f"Waiting for notifier_event from chat {echat_id} to be set to terminate", flush=True)
      notifier_event.wait()
      print(f"chat's {echat_id} notifier_event set", flush=True)
    else:
      notifier.release()

    # Discarded, as the waiting side (applicant_event.wait() needs the process to be alive)
    # We'll use a timeout where an applicant_event.wait() call is made'
    # applicant_event.set() # Set it up to enable notifier's exit (Deprecated)

  print("Bye bye, says notifier", flush=True)


def ensure_params_presence(dictionary):
  err = 0
  output = ""
  for param in dictionary:
    if (dictionary[param] == ""):
      err = 1
      output = "You must provide all requested parameters"
      break
  return err, output

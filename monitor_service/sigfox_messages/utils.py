from sigfox_messages import models, constants
from asgiref.sync import sync_to_async, async_to_sync
import asyncio, datetime, struct


def my_get_attr(obj, attr):
  return getattr(obj, attr)

def my_set_attr(obj, attr, attr_value):
  return setattr(obj, attr, attr_value)

async_my_get_attr = sync_to_async(my_get_attr, thread_sensitive=True)
async_my_set_attr = sync_to_async(my_set_attr, thread_sensitive=True)

async_Patient_Contact_filter = sync_to_async(models.Patient_Contact.objects.filter, thread_sensitive=True)
async_Device_History_filter = sync_to_async(models.Device_History.objects.filter, thread_sensitive=True)
async_Emergency_Payload_filter = sync_to_async(models.Emergency_Payload.objects.filter, thread_sensitive=True)


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

  dobj = datetime.date(int(date[6:]), int(date[3:5]), int(date[:2]))
  d = datetime.timedelta(1)
  dobj = dobj - d
  date = dobj.strftime("%d/%m/%Y")

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
    date = datetime_obj.strftime("%d/%m/%Y")

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

      if ((ebio != None) and (int(dev_hist.uplink_count)==1)): # (ebio.emsg_count > 1), but it's the first message of the day
        date = delta(date) # Purpose is getting the time of yesterday's last message
        try:
          dev_hist = models.Device_History.objects.filter(dev_conf=dev_hist.dev_conf, date=date).get()
        except models.Device_History.DoesNotExist:
          return # This should never happen. Catch exception if it does, to continue.

      datetime_obj2 = datetime.datetime(int(date[6:]), int(date[3:5]), int(date[:2]),
                                        int(dev_hist.last_msg_time[:2]), int(dev_hist.last_msg_time[3:5]),
                                        int(dev_hist.last_msg_time[6:]))
      seconds = get_sec_diff(datetime_obj, datetime_obj2)      
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
            dev_hist = models.Device_History.objects.filter(dev_conf=dev_hist.dev_conf, date=date).get()
            datetime_obj2 = datetime.datetime(int(date[6:]), int(date[3:5]), int(date[:2]),
                                              int(dev_hist.last_msg_time[:2]), int(dev_hist.last_msg_time[3:5]),
                                              int(dev_hist.last_msg_time[6:]))
            seconds = get_sec_diff(datetime_obj, datetime_obj2)

            if (seconds <= constants.MAX_TIME_DELAY):
              setattr(bio, sum_field, str(attr_value * seconds * 500))
              setattr(bio, time_field, str(seconds))
            else:
              pass # Lack of continuity upon message delivery. Leave avg_bpm/avg_ibi without updating
          except models.Device_History.DoesNotExist:
            pass
        else: # EMERGENCY_SHIP_POLICY
          # We don't have a way to determine how much time the device has been gathering samples since it booted up.
          # We know 'x' falls within 0<x<=10'30", range, but we don't know it accurately, so we start measuring device's
          # computing time from the second message onwards to update the average(s).
          pass

      elif ((ebio != None) and (int(dev_hist.uplink_count) > 1)): # (ebio.emsg_count == 1)
        datetime_obj2 = datetime.datetime(int(date[6:]), int(date[3:5]), int(date[:2]),
                                          int(dev_hist.last_msg_time[:2]), int(dev_hist.last_msg_time[3:5]),
                                          int(dev_hist.last_msg_time[6:]))
        seconds = get_sec_diff(datetime_obj, datetime_obj2)

        if (seconds <= constants.MAX_TIME_DELAY):
          setattr(bio, sum_field, (attr_value * seconds * 500))
          setattr(bio, time_field, seconds)
        else:
          pass # Lack of continuity upon message delivery. Leave fields without updating
      else:
        # We don't have a way to determine how much time the device has been gathering samples since it booted up.
        # We know 'x' falls within 0<x<=10'30", range, but we don't know it accurately, so we start measuring device's
        # computing time from the second message onwards to update the average(s).
        pass


async def notify_contact(pcontact, att_req, edate, etime):

  contact = await async_my_get_attr(pcontact, "contact")
  patient = await async_my_get_attr(pcontact, "patient")

  # Update pcontact.contact fields
  contact.echat_state = "ALERTING"
  await async_my_set_attr(pcontact, "contact", contact)
  await contact.asave()
  await pcontact.asave()

  e_spotted_msg = "---AUTOMATED EMERGENCY NOTIFICATION---\n\nHello, we send you this message "
  e_spotted_msg += "because monitor device, from patient '" + patient.name.upper() + " " + patient.surname.upper()
  e_spotted_msg += "', spotted an emergency condition (BPM LIMIT EXCEEDED). Please issue '/stop' command "
  e_spotted_msg += "to let us know that you are aware of the situation.\n\n---AUTOMATED EMERGENCY NOTIFICATION---"

  alarm_pushed_msg = "---AUTOMATED EMERGENCY NOTIFICATION---\n\nHello, we send you this message beacuse patient '"
  alarm_pushed_msg += patient.name.upper() + " " + patient.surname.upper() + "', recently pushed the alarm button "
  alarm_pushed_msg += "on his monitor device (ALARM_MSG). Please issue '/stop' command to let us know that you are "
  alarm_pushed_msg += "aware of the situation.\n\n---AUTOMATED EMERGENCY NOTIFICATION---"

  message = e_spotted_msg # Set default message

  while 1:
    try:
      emergency = await models.Emergency_Biometrics.objects.aget(patient=patient, emerg_date=edate,
                                                                 emerg_time=etime)
      break
    except models.Emergency_Biometrics.DoesNotExist:
      print("emergency does not exist")
      await asyncio.sleep(5) # Wait for it to be created on database

  while 1:
    qs = await async_Emergency_Payload_filter(emergency=emergency)
    exists = await qs.aexists()
    if exists:
      # There's probably just one payload on DB for this new emergency 
      # at this moment. Anyway, loop through the QuerySet
      async for epayload in qs:
        if epayload.ereason_payload == "Yes":
          if (epayload.msg_type == "ALARM_LIMITS_MSG" or
              epayload.msg_type == "ALARM_MSG"):
            message = alarm_pushed_msg
          break
        elif (epayload.msg_type == "ALARM_LIMITS_MSG" or
              epayload.msg_type == "ALARM_MSG"):
          message = alarm_pushed_msg
      break
    else:
      print("Waiting for payload to be saved on DB")
      asyncio.sleep(5) # Wait for it to be created on database


  async def check_stop(echat_id):

    stopped = 0
    while 1:
      try: # Query database for contact/attention_request status updates
        contact = await models.Contact.objects.aget(echat_id=echat_id)
        att_req = await models.Attention_request.objects.aget(patient=patient, emergency=emergency)
        if (contact.echat_state != "ALERTING" or att_req.status == "Attended"):
          stopped = 1
        break
      except models.Attention_request.DoesNotExist:
        print("Attention_request does not exist")
        await asyncio.sleep(5) # Wait for it to be created on database

    return stopped

  # Send 4 initial notifications
  from sigfox_messages.bot import send_message
  for e in range(1, 5):
    await send_message(contact.echat_id, message)
    await asyncio.sleep(3)
    stopped = await check_stop(contact.echat_id)
    if stopped:
      break

  async def send_loc(contact, patient):

    latitude = ""
    longitude = ""
    loc_avail = 0
    dev_conf = await async_my_get_attr(patient, "dev_conf")
    qs = await async_Device_History_filter(dev_conf=dev_conf)
    exists = await qs.aexists()

    if exists:
      dev_hist = await qs.alatest("date")
      latitude = dev_hist.last_known_latitude
      longitude = dev_hist.last_known_longitude

    if (latitude == "" or longitude == ""):
      loc_msg = "Latest patient location is not available on Database.\n"
    else:
      loc_avail = 1
      loc_msg = "Last message sent from " + patient.name.upper() + " " + patient.surname.upper()
      loc_msg += " device was on: " + dev_hist.date + " , at " + dev_hist.last_msg_time + "\n"
      loc_msg += "Location: \n"

    await send_message(contact.echat_id, loc_msg)
    if loc_avail: # Last location available
      from sigfox_messages.bot import send_location
      await send_location(contact.echat_id, latitude, longitude)

  await send_loc(contact, patient)

  if stopped:
    return

  if contact.sms_alerts == "Yes":
    # Just send one SMS alert
    pass

  await asyncio.sleep(10)
  stopped = await check_stop(contact.echat_id)
  while (stopped==0):
    await send_message(contact.echat_id, message)
    await send_loc(contact, patient)
    await asyncio.sleep(20)
    stopped = await check_stop(contact.echat_id)


def notifier(att_req, patient, date, rtc):

  async def notify():
    ntask = 0
    async for pcontact in models.Patient_Contact.objects.filter(patient=patient):
      print(f"(uplink) ntask = {ntask}")
      ntask += 1
      asyncio.create_task(notify_contact(pcontact, att_req, date, rtc))

    tasks = asyncio.all_tasks()
    current_task = asyncio.current_task()
    tasks.remove(current_task)
    await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)

  asyncio.run(notify())
  print("Bye bye, says notifier")


def ensure_params_presence(dictionary):
  err = 0
  output = ""
  for param in dictionary:
    if (dictionary[param] == ""):
      err = 1
      output = "You must provide all requested parameters"
      break
  return err, output

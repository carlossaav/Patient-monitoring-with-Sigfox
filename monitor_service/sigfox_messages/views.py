from django.http import HttpResponse, Http404, HttpResponseBadRequest, JsonResponse
from http import HTTPStatus
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from sigfox_messages import models, constants
from sigfox_messages.utils import send_message, send_location, async_my_get_attr, async_my_set_attr
from sigfox_messages.utils import async_Device_History_filter, async_Emergency_Payload_filter
from multiprocessing import Process
import asyncio, datetime, struct, json


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


@require_GET
@csrf_exempt
# def downlink(request):
def downlink(request, dev_id):

  datetime_obj = datetime.datetime.now()
  date = datetime_obj.strftime("%d/%m/%Y") # dd/mm/yy format
  rtc = datetime_obj.strftime("%H:%M:%S")  # hh:mm:ss format

  try:
    dev_conf = models.Device_Config.objects.get(dev_id=dev_id)
  except models.Device_Config.DoesNotExist:
    output = "Device with device id " + dev_id + " does not exist"
    raise Http404(output)

  try:
    dev_hist = models.Device_History.objects.filter(dev_conf=dev_conf, date=date).get()
  except models.Device_History.DoesNotExist: # Create new history for dev_conf.dev_id device
    dev_hist = models.Device_History(dev_conf=dev_conf, date=date, running_since=rtc,
                                                    uplink_count="0", downlink_count="0")

  dev_hist.downlink_count = str(int(dev_hist.downlink_count) + 1)
  dev_hist.save()

  # Build payload following rtc:bt:msg:ub:lb:bx downlink payload format

  l = [int(rtc[:2]), int(rtc[3:5]), int(rtc[6:])]  # hour, minute and sec

  payload = ""
  payload += format(l[0], "05b")
  for e in l[1:]:
    payload += format(e, "06b")

  payload += format(int(dev_conf.bpm_limit_window), "07b")   # bt
  payload += format(int(dev_hist.uplink_count), "08b")       # msg  
  payload += format(int(dev_conf.higher_bpm_limit), "08b")   # ub
  payload += format(int(dev_conf.lower_bpm_limit), "08b")    # lb
  payload += format(int(dev_conf.min_delay), "016b")         # bx

  payload = hex(int(payload, 2))[2:] # Convert to hex string. Skip '0x' chars

  d = {dev_id: {"downlinkData": payload}}
  response = JsonResponse(d)
  print("(downlink) response.content = ", response.content)
  print("(downlink) response = ", response)
  return response


async def notify_contact(pcontact, att_req, edate, etime):

  contact = await async_my_get_attr(pcontact, "contact")
  patient = await async_my_get_attr(pcontact, "patient")

  # Update pcontact.contact fields
  contact.echat_state = "ALERTING"
  await async_my_set_attr(pcontact, "contact", contact)
  await contact.asave()
  await pcontact.asave()

  e_spotted_msg = "---AUTOMATED EMERGENCY NOTIFICATION---\n\nHello, we send you this message because monitor device, "
  e_spotted_msg += "from patient '" + patient.name.upper() + " " + patient.surname.upper() + "', spotted an emergency condition (BPM LIMIT EXCEEDED)"
  e_spotted_msg += ". Please issue '/stop' command to let us know that you are aware of the situation.\n\n"
  e_spotted_msg += "---AUTOMATED EMERGENCY NOTIFICATION---"

  alarm_pushed_msg = "---AUTOMATED EMERGENCY NOTIFICATION---\n\nHello, we send you this message beacuse patient '"
  alarm_pushed_msg += patient.name.upper() + " " + patient.surname.upper() + "', recently pushed the alarm button on his monitor device (ALARM_MSG)"
  alarm_pushed_msg += ". Please issue '/stop' command to let us know that you are aware of the situation.\n\n"
  alarm_pushed_msg += "---AUTOMATED EMERGENCY NOTIFICATION---"

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


@require_POST
@csrf_exempt
def uplink(request):

  datetime_obj = datetime.datetime.now()
  date = datetime_obj.strftime("%d/%m/%Y") # dd/mm/yy format
  rtc = datetime_obj.strftime("%H:%M:%S")  # hh:mm:ss format

  try:
    print()
    print("(uplink) request.body =", request.body)
    body = json.loads(request.body)
    print("body = json.loads(request.body)")
    print("(uplink) body =", body)
    print("(uplink) type(body) =", type(body))

    dev_id = body["device"]
    payload = body["data"]
    dev_conf = models.Device_Config.objects.get(dev_id=dev_id)
    patient = models.Patient.objects.get(dev_conf=dev_conf)
  except KeyError:
    output = "device id or payload data not provided, return 400"
    print(output)
    return HttpResponseBadRequest(output)
  except models.Device_Config.DoesNotExist: # We can't relate payload data to any patient
    output = "Device with device id " + dev_id + " does not exist"
    print(output)
    raise Http404(output)
  except models.Patient.DoesNotExist: # We can't relate payload data to any patient
    output = "Patient with device id " + dev_id + " wasn't found"
    print(output)
    raise Http404(output)


  new_hist = 0
  migrate_bio = 0
  try:
    # Should return a single instance or nothing (exception)
    dev_hist = models.Device_History.objects.get(dev_conf=dev_conf, date=date)
    if (int(dev_hist.uplink_count) == 0):
      qs = models.Device_History.objects.filter(dev_conf=dev_conf).order_by("-date")
      if (len(qs) > 1):
        migrate_bio = 1
        last_date = qs[1].date # Get the latest date when an uplink message was sent (prior to this one)
  except models.Device_History.DoesNotExist:
    new_hist = 1 # Create a new history entry for the device
    try:
      d = models.Device_History.objects.filter(dev_conf=dev_conf).latest("date")
      last_date = d.date
      migrate_bio = 1
    except models.Device_History.DoesNotExist:
      pass # No messages stored from this device. This is the first one

    dev_hist = models.Device_History(dev_conf=dev_conf, date=date, running_since=rtc, last_msg_time=rtc,
                                                    uplink_count="0", downlink_count="0")

  # Update uplink_count 
  dev_hist.uplink_count = str(int(dev_hist.uplink_count) + 1)

  new_bio_24 = 0
  try:
    biometrics_24 = models.Biometrics_24.objects.get(patient=patient)
  except models.Biometrics_24.DoesNotExist:
    migrate_bio = 0
    new_bio_24 = 1

  if migrate_bio: # Migrate data on Biometrics_24 to Biometrics
    new_bio_24 = 1
    models.Biometrics.objects.create(patient=patient,
                                     date=last_date,
                                     avg_bpm=biometrics_24.avg_bpm, 
                                     avg_ibi=biometrics_24.avg_ibi,
                                     max_bpm=biometrics_24.max_bpm,
                                     max_ibi=biometrics_24.max_ibi,
                                     min_bpm=biometrics_24.min_bpm,
                                     min_ibi=biometrics_24.min_ibi,
                                     lower_range=biometrics_24.lower_range,
                                     second_range=biometrics_24.second_range,
                                     third_range=biometrics_24.third_range,
                                     higher_range=biometrics_24.higher_range,
                                     last_temp=biometrics_24.last_temp,
                                     avg_temp=biometrics_24.avg_temp,
                                     max_temp=biometrics_24.max_temp,
                                     min_temp=biometrics_24.min_temp,
                                     last_alarm_time=biometrics_24.last_alarm_time,
                                     last_limit_time=biometrics_24.last_limit_time,
                                     last_elimit_time=biometrics_24.last_elimit_time)


  if new_bio_24: # Following payload data will "reset" Biometrics_24 (first payload to write on it)
    biometrics_24 = models.Biometrics_24(patient=patient)


  # Process the payload, update related fields on tables (following Uplink Payload Formats are defined in Readme.md)
  # print(f"(uplink) payload = {payload}")
  bin_data = bin(int(payload, 16))[2:]

  # print(f"(uplink) bin_data (before) = {bin_data}")

  if (len(bin_data) <= 80):
    bin_data = bin_data.zfill(80) # 10-byte packet
  else:
    bin_data = bin_data.zfill(96) # 12-byte packet

  # print(f"(uplink) bin_data (after) = {bin_data}")
  # print(f"(uplink) len(bin_data) = {len(bin_data)}")

  # First 6 fields are common to all payload formats

  print("(uplink) Uplink message received! Printing fields..")
  print()
  emergency = retrieve_field(bin_data, 0, 1)                   # emergency field
  print(f"(uplink) emergency = {emergency}")
  ereason_payload = retrieve_field(bin_data, 1, 1)             # emergency reason field
  print(f"(uplink) ereason = {ereason_payload}")
  shipment_policy = retrieve_field(bin_data, 2, 2)             # shipment_policy field
  print(f"(uplink) shipment_policy = {shipment_policy}")
  msg_type = retrieve_field(bin_data, 4, 3)                    # msg_type field
  print(f"(uplink) msg_type = {msg_type}")

  new_e = 0
  emerg_update = 0
  if emergency:
    emerg_update = 1
  try:
    ebio = models.Emergency_Biometrics.objects.filter(patient=patient).latest("emerg_date", "emerg_time")
    if emergency:
      datetime_obj2 = datetime.datetime(int(ebio.emerg_date[6:]), int(ebio.emerg_date[3:5]),
                                        int(ebio.emerg_date[:2]), int(ebio.emerg_time[:2]),
                                        int(ebio.emerg_time[3:5]), int(ebio.emerg_time[6:]))
      # check emergency creation/reactivation
      seconds = get_sec_diff(datetime_obj, datetime_obj2)
      if (seconds > constants.NEW_EMERG_DELAY):
        ebio.active = "No"
        ebio.save() # As we are creating a new one, update last emergency (actual ebio object) 'active' field on DB.
        new_e = 1
      elif (ebio.active == "No"): # Still on the same 'logical' emergency, reactivate it
        ebio.active = "Yes"

    elif (ebio.active == "Yes"): # emergency == 0 (Emergency finished)
      ebio.active = "No"
      emerg_update = 1
  except models.Emergency_Biometrics.DoesNotExist:
    if emergency:
      new_e = 1

  try:
    loc_info = body["computedLocation"]
    print(f"loc_info = {loc_info}")

    loc_status = loc_info["status"]
    if (loc_status == 1): # Geolocation successlly computed
      latitude = loc_info["lat"]
      print(f"type(latitude) = {type(latitude)}")
      print(f"latitude = {latitude}")
      longitude = loc_info["lng"]
      print(f"type(longitude) = {type(longitude)}")
      print(f"longitude = {longitude}")
      # location = google_maps call (i.e "Calle San Juan, Zamora") // Consultar que posibilidades ofrece el API
      # No llamar al API cada vez que recibes un mensaje (demasiadas llamadas). Hacerlo bien cuando cambien las coordenadas(implica almacenar coordenadas y comparar # las recibidas con las almacenadas) o consultar cada cierto tiempo (1 vez cada 20 minutos en condiciones normales y una cada 5' en emergencias, por ejemplo)
      dev_hist.last_known_latitude = str(latitude)
      dev_hist.last_known_longitude = str(longitude)
      # dev_hist.last_known_location = str(location)
      dev_hist.save() # Save it here so it can be available for potential Telegram notifications
    else:
      pass # Do not update latitude/longitude/location
  except KeyError:
    print("Geolocation not available")
    pass # Do not update latitude/longitude/location 


  if new_e: # create new emergency, Attention request
    ebio = models.Emergency_Biometrics(patient=patient, emerg_date=date, emerg_time=rtc,
                                       emsg_count="0", active="Yes")
    att_req = models.Attention_request(emergency=ebio, patient=patient, request_date=date,
                                                      request_time=rtc, request_type="Emergency",
                                                      status="Ongoing")
    doctor_req = models.Doctor_Request(attention_request=att_req, patient=patient, doctor=patient.doctor,
                                         request_state="Pending")

    def notifier(att_req):

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

    p = Process(target=notifier, args=(att_req, ))
    p.start()


  if emergency:
    ebio.emsg_count = str(int(ebio.emsg_count) + 1)


  # Update biometrics timestamps
  if (msg_type == constants.ALARM_MSG):
    biometrics_24.last_alarm_time = rtc
  elif (msg_type == constants.LIMITS_MSG):
    biometrics_24.last_limit_time = rtc
  elif (msg_type == constants.ALARM_LIMITS_MSG):
    biometrics_24.last_alarm_time = rtc
    biometrics_24.last_limit_time = rtc

  # Retrieve format bits from rpv field
  payload_format = bin_data[10] + bin_data[21] + bin_data[32]  # payload format
  payload_format = int(payload_format, 2)
  print(f"(uplink) payload_format = {payload_format}")

  avg_bpm = 0
  avg_ibi = 0
  max_bpm = 0
  max_ibi = 0
  min_bpm = 0
  min_ibi = 0
  lower_range = 0
  second_range = 0
  third_range = 0
  higher_range = 0
  temp = 0.0
  elapsed_ms = 0

  if (payload_format != 4): # Retrieve range ids and percentages
    l = []
    ibit = 7
    per_sum = 0
    counter = 0
    p = [0, 0, 0, 0]
    while (counter < 3):
      print(f"(uplink) counter = {counter}")
      range_id = retrieve_field(bin_data, ibit, 3)
      print(f"(uplink) range_id = {range_id}")
      percentage = retrieve_field(bin_data, ibit+4, 7)
      print(f"(uplink) percentage = {percentage}")
      range_name = get_attr_name(range_id)
      update_ranges(dev_hist, range_name, percentage, biometrics_24, None)
      if emergency:
        update_ranges(dev_hist, range_name, percentage, None, ebio)
      l.append(range_id)
      per_sum += percentage
      ibit += 11
      counter += 1
      if (range_id in range(4)):
        p[range_id] = percentage

    for r_id in range(4):
      if r_id not in l:
        excluded_id = r_id
        break

    print(f"(uplink) excluded_id = {excluded_id}")
    range_name = get_attr_name(excluded_id)
    print(f"(uplink) range_name = {range_name}")
    excluded_percentage = (100 - per_sum)
    print(f"(uplink) excluded_percentage = {excluded_percentage}")
    update_ranges(dev_hist, range_name, excluded_percentage, biometrics_24, None)
    if emergency:
      update_ranges(dev_hist, range_name, excluded_percentage, None, ebio)

    if (excluded_id in range(4)):
      p[excluded_id] = excluded_percentage

    lower_range = p[0]
    second_range = p[1]
    third_range = p[2]
    higher_range = p[3]

    avg_bpm = retrieve_field(bin_data, 40, 8)                    # Average Beats Per Minute
    print(f"(uplink) avg_bpm = {avg_bpm}")
    update_bpm_ibi(dev_hist, "avg_bpm", avg_bpm, biometrics_24, None, datetime_obj, shipment_policy)
    if emergency:
      update_bpm_ibi(dev_hist, "avg_bpm", avg_bpm, None, ebio, datetime_obj, shipment_policy)

  # Next fields vary depending on which payload_format we're dealing with

  if (payload_format==0 or payload_format==1 or payload_format==5):
    max_bpm = retrieve_field(bin_data, 48, 8)                  # Highest record of Beats Per Minute
    print(f"(uplink) max_bpm = {max_bpm}")
    min_bpm = retrieve_field(bin_data, 56, 8)                  # Lowest record of Beats Per Minute
    print(f"(uplink) min_bpm = {min_bpm}")
    update_bpm_ibi(dev_hist, "max_bpm", max_bpm, biometrics_24, None)
    update_bpm_ibi(dev_hist, "min_bpm", min_bpm, biometrics_24, None)
    if emergency:
      update_bpm_ibi(dev_hist, "max_bpm", max_bpm, None, ebio)
      update_bpm_ibi(dev_hist, "min_bpm", min_bpm, None, ebio)

    if ((max_bpm > int(dev_conf.higher_ebpm_limit)) or (min_bpm < int(dev_conf.lower_ebpm_limit))):
      biometrics_24.last_elimit_time = rtc

  if (payload_format==0 or payload_format==2 or payload_format==4):
    if payload_format == 4: # 10 byte packet
      temp = retrieve_temp(bin_data, 48, 32)                    # Retrieve Temperature
      print(f"(uplink) temp = {temp}")
    else:
      temp = retrieve_temp(bin_data, 64, 32)
      print(f"(uplink) temp = {temp}")
    update_temp(dev_hist, temp, biometrics_24, None)
    if emergency:
      update_temp(dev_hist, temp, None, ebio)

  if (payload_format==2 or payload_format==3 or payload_format==6):
    avg_ibi = retrieve_field(bin_data, 48, 16)                 # Average InterBeat Interval
    print(f"(uplink) avg_ibi = {avg_ibi}")
    update_bpm_ibi(dev_hist, "avg_ibi", avg_ibi, biometrics_24, None, datetime_obj, shipment_policy)
    if emergency:
      update_bpm_ibi(dev_hist, "avg_ibi", avg_ibi, None, ebio, datetime_obj, shipment_policy)

  if (payload_format==1 or payload_format==3 or payload_format==5 or payload_format==6):
    max_ibi = retrieve_field(bin_data, 64, 16)                 # Highest record of Interbeat interval
    print(f"(uplink) max_ibi = {max_ibi}")
    min_ibi = retrieve_field(bin_data, 80, 16)                 # Lowest record of Interbeat interval
    print(f"(uplink) min_ibi = {min_ibi}")
    update_bpm_ibi(dev_hist, "max_ibi", max_ibi, biometrics_24, None)
    update_bpm_ibi(dev_hist, "min_ibi", min_ibi, biometrics_24, None)
    if emergency:
      update_bpm_ibi(dev_hist, "max_ibi", max_ibi, None, ebio)
      update_bpm_ibi(dev_hist, "min_ibi", min_ibi, None, ebio)

  if (payload_format == 7):
    elapsed_ms = retrieve_field(bin_data, 64, 32)              # Elapsed milliseconds since the recovery message was stored
    print(f"(uplink) elapsed_ms = {elapsed_ms}")


  # Add individual payload fields to Emergency_Payload table

  if emergency:
    if ereason_payload:
      ereason = "Yes"
    else:
      ereason = "No"

    if (msg_type == constants.ALARM_MSG):
      m_type = "ALARM_MSG"
    elif (msg_type == constants.LIMITS_MSG):
      m_type = "LIMITS_MSG"
    elif (msg_type == constants.ALARM_LIMITS_MSG):
      m_type = "ALARM_LIMITS_MSG"
    elif (msg_type == constants.ERROR_MSG):
      m_type = "ERROR_MSG"
    elif (msg_type == constants.REC_ALARM_MSG):
      m_type = "REC_ALARM_MSG"
    elif (msg_type == constants.REC_LIMITS_MSG):
      m_type = "REC_LIMITS_MSG"
    elif (msg_type == constants.REC_ALARM_LIMITS_MSG):
      m_type = "REC_ALARM_LIMITS_MSG"
    elif (msg_type == constants.REPORT_MSG):
      m_type = "REPORT_MSG"

    epayload = models.Emergency_Payload(emergency=ebio, ereason_payload=ereason,
                                        msg_type=m_type, payload_format=str(payload_format),
                                        avg_bpm=str(avg_bpm), avg_ibi=str(avg_ibi),
                                        max_bpm=str(max_bpm), max_ibi=str(max_ibi),
                                        min_bpm=str(min_bpm), min_ibi=str(min_ibi),
                                        lower_range=str(lower_range),
                                        second_range=str(second_range),
                                        third_range=str(third_range),
                                        higher_range=str(higher_range),
                                        temp=str(temp), elapsed_ms=str(elapsed_ms))

  # Update dev_hist fields
  dev_hist.last_msg_time = rtc
  dev_hist.last_dev_state = "Functional"
  if (msg_type == constants.ERROR_MSG):
    if (payload_format == 4):
      dev_hist.last_dev_state = "Pulse sensor error"
    else:
      dev_hist.last_dev_state = "Temperature sensor error"

  dev_hist.save()
  biometrics_24.save()
  if emerg_update:
    ebio.save()
  if emergency:
    epayload.save()
  if new_e:
    att_req.save()
    doctor_req.save()
  if new_hist:
    models.Patient_Device_History.objects.create(dev_hist=dev_hist, patient=patient)

  return HttpResponse(status=HTTPStatus.NO_CONTENT)

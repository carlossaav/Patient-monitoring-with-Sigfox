#from django.shortcuts import render
from django.http import HttpResponse, Http404, HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST
from sigfox_messages import models, constants
from sigfox_messages.utils import send_message, send_location
# from threading import Thread
from multiprocessing import Process
import asyncio
import datetime
import struct

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
  elif range_id == 3:
    return "higher_range"


# Substract one day to the given date
def delta(date):

  dobj = datetime.date(int(date[6:]), int(date[3:5]), int(date[:2]))
  d = datetime.timedelta(1)
  dobj = dobj - d
  date = dobj.strftime("%d/%m/%Y")

  return date


def get_sec_diff(datetime_obj, datetime_obj2):

  dojb = datetime_obj - datetime_obj2

  return dobj.seconds


def get_bio(dev_hist, bio_24=None, ebio=None):

  if (bio_24 != None):
    bio = bio_24
    msg_count = int(dev_hist.uplink_count)
  elif (ebio != None):
    bio = ebio
    msg_count = int(ebio.msg_count)
  else: # Failed update
    bio = None
    msg_count = None

  return bio, msg_count


def update_ranges(dev_hist, attr, attr_value, bio_24=None, ebio=None):

  bio, msg_count = get_bio(dev_hist, bio_24, ebio)

  if (bio == None): # Failed update
    return

  # bpm ranges and related fields are set directly
  range_sum_field = attr + "_sum"
  if (msg_count == 1):
    setattr(bio, range_sum_field, str(attr_value))
  else:
    setattr(bio, range_sum_field, str(attr_value + int(getattr(bio, range_sum_field))))
  setattr(bio, attr, str(int(getattr(bio, range_sum_field))/msg_count))


def update_temp(dev_hist, attr, attr_value, bio_24=None, ebio=None):

  bio, msg_count = get_bio(dev_hist, bio_24, ebio)

  if (bio == None): # Failed update
    return

  # Temperature related attributes are set directly
  bio.last_temp = str(attr_value)

  if (msg_count > 1):
    bio.sum_temp = str(float(bio.sum_temp) + attr_value)
    if (attr_value < float(bio.min_temp)):
      bio.min_temp = str(attr_value)
    elif (attr_value > float(bio.max_temp)):
      bio.max_temp = str(attr_value)
  else:
    bio.sum_temp = str(attr_value)
    bio.min_temp = str(attr_value)
    bio.max_temp = str(attr_value)

  bio.avg_temp = str(round((float(bio.sum_temp)/msg_count), 3))


def update_bpm_ibi(dev_hist, attr, attr_value, bio_24=None, ebio=None, datetime_obj=None, shipment_policy=0):

  bio, msg_count = get_bio(dev_hist, bio_24, ebio)

  if (bio == None): # Failed update
    return

  if (datetime_obj != None): # on average updates
    date = datetime_obj.strftime("%d/%m/%Y")

  if (msg_count > 1):
    if ((attr == "max_bpm") and (attr_value > int(bio.max_bpm))):
      bio.max_bpm = str(attr_value)
    elif ((attr == "min_bpm") and (attr_value < int(bio.min_bpm))):
      bio.min_bpm = str(attr_value)
    elif ((attr == "max_ibi") and (attr_value > int(bio.max_ibi))):
      bio.max_ibi = str(attr_value)
    elif ((attr == "min_ibi") and (attr_value < int(bio.min_ibi))):
      bio.min_ibi = str(attr_value)
    elif ((attr == "avg_bpm") or (attr == "avg_ibi")):

      if ((ebio != None) and (int(dev_hist.uplink_count)==1)): # (ebio.msg_count > 1), but it's the first message of the day
        date = delta(date) # Purpose is getting the time of yesterday's last message
        try:
          dev_hist = models.Device_History.objects.filter(dev_conf=dev_hist.dev_conf, date=date).get()
        except models.Device_History.DoesNotExist:
          return # This should never happen. Catch exception if it does, to continue.

      datetime_obj2 = datetime.datetime(int(date[6:]), int(date[3:5]), int(date[:2]),
                                        int(dev_hist.last_msg_time[:2]), int(dev_hist.last_msg_time[3:5]),
                                        int(dev_hist.last_msg_time[6:]))
      seconds = get_sec_diff(datetime_obj, datetime_obj2)

      if (seconds <= constants.MAX_TIME_DELAY):
        sum_field = "sum_" + attr[4:]
        time_field = attr[4:] + "_time"
        partial_sum = attr_value * (seconds * 500) # 500 samples per second
        setattr(bio, sum_field, str(int(getattr(bio, sum_field)) + partial_sum))
        setattr(bio, time_field, str(int(getattr(bio, time_field)) + seconds))
        setattr(bio, attr, str(round(int(getattr(bio, sum_field))/(int(getattr(bio, time_field)) * 500))))
      else:
        pass # Lack of continuity upon message delivery. Leave avg_bpm/avg_ibi without updating
  else:
    # First message of the day/emergency or both
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

      elif ((ebio != None) and (int(dev_hist.uplink_count) > 1)): # EMERGENCY_SHIP_POLICY; (ebio.msg_count == 1)
        datetime_obj2 = datetime.datetime(int(date[6:]), int(date[3:5]), int(date[:2]),
                                          int(dev_hist.last_msg_time[:2]), int(dev_hist.last_msg_time[3:5]),
                                          int(dev_hist.last_msg_time[6:]))
        seconds = get_sec_diff(datetime_obj, datetime_obj2)

        if (seconds <= constants.MAX_TIME_DELAY):
          sum_field = "sum_" + attr[4:]
          time_field = attr[4:] + "_time"
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

  return JsonResponse({dev_id: {"downlinkData": payload}})



async def notify_contact(pcontact, att_req):

  # Update pcontact.contact fields
  pcontact.contact.echat_state = "ALERTING"
  pcontact.contact.comm_status = "Notifying"
  await pcontact.asave()
  # await pcontact.contact.asave()

  message = "---AUTOMATED EMERGENCY NOTIFICATION---\n\nHello, we send you this message because monitor device, "
  message += "from patient " + pcontact.patient.name + " " + pcontact.patient.surname + ", spotted an emergency "
  message += "condition.\nPlease issue '/stop' command to let us know that you are aware of the situation. "
  message += "You can visit https://www.com/sigfox_messages/ to get the latest biometrics from this patient.\n\n"
  message += "---AUTOMATED EMERGENCY NOTIFICATION---"

  for e in range(1, 5): # send 4 initial notifications
    await send_message(pcontact.contact.echat_id, message)
    await asyncio.sleep(3)

  async def send_loc(contact):

    loc_avail = 0
    if (contact.last_known_latitude == ""
        or contact.last_known_longitude == ""):
      loc_msg = "Last patient's location not available on Database.\n"
    else:
      loc_avail = 1
      loc_msg = "Last known patient's location:\n"

    await send_message(contact.echat_id, loc_msg)
    if loc_avail: # Last location available
      await send_location(contact.echat_id, contact.last_known_latitude,
                          contact.last_known_longitude)

  await send_loc(pcontact.contact)

  if pcontact.contact.sms_alerts == "Yes":
    # Just send one SMS alert
    pass

  await asyncio.sleep(10)
  while 1:
    try:
      contact = models.Contact.objects.get(echat_id=pcontact.contact.echat_id)
      att_req = models.Attention_request.objects.get(id=att_req.id)
      if ((contact.comm_status == "Received") or
          (att_req.status == "Attended")):
        return
      await send_message(contact.echat_id, message)
      await send_loc(contact)
      await asyncio.sleep(30)
    except models.Contact.DoesNotExist:
      return
    except models.Attention_request.DoesNotExist:
      return


@require_POST
def uplink(request):

  datetime_obj = datetime.datetime.now()
  date = datetime_obj.strftime("%d/%m/%Y") # dd/mm/yy format
  rtc = datetime_obj.strftime("%H:%M:%S")  # hh:mm:ss format

  try:
    dev_conf = models.Device_Config.objects.get(dev_id=request.POST["device"])
    patient = models.Patient.objects.get(dev_conf=dev_conf)
  except KeyError:
    return HttpResponseBadRequest("device id not provided")
  except models.Device_Config.DoesNotExist: # We can't relate payload data to any patient
    output = "Device with device id " + request.POST["device"] + " does not exist"
    raise Http404(output)
  except models.Patient.DoesNotExist: # We can't relate payload data to any patient
    output = "Patient with device id " + request.POST["device"] + " wasn't found"
    raise Http404(output)

  try:
    payload = request.POST["data"]
  except KeyError:
    return HttpResponseBadRequest("payload not provided")

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
  except Biometrics_24.DoesNotExist:
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
  bin_data = bin(int(data, 16))[2:]

  if (len(bin_data) <= 80):
    bin_data = bin_data.zfill(80) # 10-byte packet
  else:
    bin_data = bin_data.zfill(96) # 12-byte packet

  # First 6 fields are common to all payload formats

  emergency = retrieve_field(bin_data, 0, 1)                   # emergency field
  econd_payload = retrieve_field(bin_data, 1, 1)               # emergency reason field
  shipment_policy = retrieve_field(bin_data, 2, 2)             # shipment_policy field
  msg_type = retrieve_field(bin_data, 4, 3)                    # msg_type field

  # if emergency:
      # check emergency already exists on database
      # if not, create emergency on database, add data to database (Emergency_Biometrics), create attention request
        # Initiate calling to SMS and Whatssap Systems (background process), do not rely on requests to the Monitor service (uplink view to be executed)
        # Remember to set Contact.echat_state to ALERTING
      # else (ongoing emergency)
        # Merge payload data with Emergency_Biometrics
        # When emergency ends (device perspective), emergency field equals to 0. i.e next payload will be added to basic Biometrics tables, not to Emergency_Biometrics
        # Emergency will continue active until someone marks it as attended accessing a URL, or from the web

  emerg_update = 0
  new_e = 0
  try:
    ebio = models.Emergency_Biometrics.objects.filter(patient=patient).latest("emerg_date", "emerg_time")
    if emergency:
      if (shipment_policy == constants.EMERGENCY_SHIP_POLICY):
        emerg_update = 1
        if (ebio.active == "No"):
          seconds = get_sec_diff(datetime_obj, int(ebio.emerg_date[:2]), int(ebio.emerg_date[3:5]),
                                 int(ebio.emerg_date[6:]), int(ebio.emerg_time[:2]),
                                 int(ebio.emerg_time[3:5]), int(ebio.emerg_time[6:]))
          if (seconds <= constants.NEW_EMERG_DELAY):
            ebio.active = "Yes"
          else:
            new_e = 1
      elif ((shipment_policy == constants.RECOVERY_SHIP_POLICY) and (ebio.active=="No")):
        # ebio.active = "Yes" # Reactivate emergency
        # emerg_update = 1
        # si hacemos esto, se nos complica la diferenciacion entre tramos de emergencia (comprobamos emergencia activa eon este campo)
        # por otro lado, seria lo suyo darle un sentido al hecho de enviar mensajes de emergencia en rpol. Enviar payload individual por SMS? i.e.?
        # ebit==1 en medio de rpol ocurre porque salta condicion de emergencia por pulsacion o Elimit, pero se continua en rpol, 
        # pues se viene de una epol por alguno de esos motivos.
        pass
    elif (ebio.active == "Yes"): # emergency == 0
      ebio.active = "No"
      emerg_update = 1
  except models.Emergency_Biometrics.DoesNotExist:
    if (shipment_policy == constants.EMERGENCY_SHIP_POLICY):
      new_e = 1
      emerg_update = 1

  try:
    latitude, longitude = request.POST["geolocation"]

    dev_hist.last_known_latitude = str(latitude)
    dev_hist.last_known_longitude = str(longitude)

    # location = google_maps call (i.e "Calle San Juan, Zamora") // Consultar que posibilidades ofrece el API
    # No llamar al API cada vez que recibes un mensaje (demasiadas llamadas). Hacerlo bien cuando cambien las coordenadas(implica almacenar coordenadas y comparar # las recibidas con las almacenadas) o consultar cada cierto tiempo (1 vez cada 20 minutos en condiciones normales y una cada 5' en emergencias, por ejemplo)
    dev_hist.last_known_location = str(location)
    dev_hist.save()
  except KeyError:
    pass  # Do not update latitude/longitude/location 


  if new_e: # create new emergency, Attention request
    ebio = models.Emergency_Biometrics(patient=patient, emerg_date=date, emerg_time=rtc,
                                       msg_count="0", active="Yes")
    att_req = models.Attention_request.objects.create(emergency=ebio, patient=patient, request_date=date,
                                                      request_time=rtc, request_type="Emergency",
                                                      request_state="Ongoing")
    models.Doctor_Request.objects.create(attention_request=att_req, patient=patient, doctor=patient.doctor,
                                         request_state="Pending")

    def notifier(pcontact, att_req):

      async def notify():
        async for pcontact in models.Patient_Contact.objects.filter(patient=patient):
          task = asyncio.create_task(notify_contact(pcontact, att_req))
          await task

      asyncio.run(notify)

    p = Process(target=notifier, args=(pcontact, att_req))
    p.start()


  if (shipment_policy == constants.EMERGENCY_SHIP_POLICY):
    ebio.msg_count = str(int(ebio.msg_count) + 1)


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
    while (counter != 3):
      range_id = retrieve_field(bin_data, ibit, 3)
      percentage = retrieve_field(bin_data, ibit+4, 7)
      range_name = get_attr_name(range_id)
      update_ranges(dev_hist, range_name, percentage, biometrics_24, None)
      if (shipment_policy == constants.EMERGENCY_SHIP_POLICY):
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

    excluded_percentage = (100 - per_sum)
    range_name = get_attr_name(excluded_id)
    update_ranges(dev_hist, range_name, excluded_percentage, biometrics_24, None)
    if (shipment_policy == constants.EMERGENCY_SHIP_POLICY):
      update_ranges(dev_hist, range_name, excluded_percentage, None, ebio)
    
    if (excluded_id in range(4)):
      p[excluded_id] = excluded_percentage
    
    lower_range = p[0]
    second_range = p[1]
    third_range = p[2]
    higher_range = p[3]

    avg_bpm = retrieve_field(bin_data, 40, 8)                    # Average Beats Per Minute
    update_bpm_ibi(dev_hist, "avg_bpm", avg_bpm, biometrics_24, None, datetime_obj, shipment_policy)
    if (shipment_policy == constants.EMERGENCY_SHIP_POLICY):
      update_bpm_ibi(dev_hist, "avg_bpm", avg_bpm, None, ebio, datetime_obj, shipment_policy)

  # Next fields vary depending on which payload_format we're dealing with

  if (payload_format==0 or payload_format==1 or payload_format==5):
    max_bpm = retrieve_field(bin_data, 48, 8)                  # Highest record of Beats Per Minute
    min_bpm = retrieve_field(bin_data, 56, 8)                  # Lowest record of Beats Per Minute
    update_bpm_ibi(dev_hist, "max_bpm", max_bpm, biometrics_24, None)
    update_bpm_ibi(dev_hist, "min_bpm", min_bpm, biometrics_24, None)
    if (shipment_policy == constants.EMERGENCY_SHIP_POLICY):
      update_bpm_ibi(dev_hist, "max_bpm", max_bpm, None, ebio)
      update_bpm_ibi(dev_hist, "min_bpm", min_bpm, None, ebio)

    if ((max_bpm > dev_conf.higher_ebpm_limit) or (min_bpm < dev_conf.lower_ebpm_limit)):
      biometrics_24.last_elimit_time = rtc

  if (payload_format==0 or payload_format==2 or payload_format==4):
    if payload_format == 4: # 10 byte packet
      temp = retrieve_temp(bin_data, 48, 32)                    # Retrieve Temperature
    else:
      temp = retrieve_temp(bin_data, 64, 32)
    update_temp(dev_hist, "temp", temp, biometrics_24, None)
    if (shipment_policy == constants.EMERGENCY_SHIP_POLICY):
      update_temp(dev_hist, "temp", temp, None, ebio)

  if (payload_format==2 or payload_format==3 or payload_format==6):
    avg_ibi = retrieve_field(bin_data, 48, 16)                 # Average InterBeat Interval
    update_bpm_ibi(dev_hist, "avg_ibi", avg_ibi, biometrics_24, None, datetime_obj, shipment_policy)
    if (shipment_policy == constants.EMERGENCY_SHIP_POLICY):
      update_bpm_ibi(dev_hist, "avg_ibi", avg_ibi, None, ebio, datetime_obj, shipment_policy)

  if (payload_format==1 or payload_format==3 or payload_format==5 or payload_format==6):
    max_ibi = retrieve_field(bin_data, 64, 16)                 # Highest record of Interbeat interval
    min_ibi = retrieve_field(bin_data, 80, 16)                 # Lowest record of Interbeat interval
    update_bpm_ibi(dev_hist, "max_ibi", max_ibi, biometrics_24, None)
    update_bpm_ibi(dev_hist, "min_ibi", min_ibi, biometrics_24, None)
    if (shipment_policy == constants.EMERGENCY_SHIP_POLICY):
      update_bpm_ibi(dev_hist, "max_ibi", max_ibi, None, ebio)
      update_bpm_ibi(dev_hist, "min_ibi", min_ibi, None, ebio)

  if (payload_format == 7):
    elapsed_ms = retrieve_field(bin_data, 64, 32)              # Elapsed milliseconds since the recovery message was stored


  if (shipment_policy == constants.EMERGENCY_SHIP_POLICY): # Add individual payload fields to Emergency_Payload table
    if econd_payload:
      econd = "Yes"
    else:
      econd = "No"

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

    epayload = models.Emergency_Payload.objects.create(ebio=ebio, econd_payload=econd,
                                                       msg_type=m_type, payload_format=payload_format,
                                                       avg_bpm=avg_bpm, avg_ibi=avg_ibi,
                                                       max_bpm=max_bpm, max_ibi=max_ibi,
                                                       min_bpm=min_bpm, min_ibi=min_ibi,
                                                       lower_range=lower_range,
                                                       second_range=second_range,
                                                       third_range=third_range,
                                                       higher_range=higher_range,
                                                       temp=temp, elapsed_ms=elapsed_ms)

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
  if new_hist:
    models.Patient_Device_History.objects.create(dev_hist=dev_hist, patient=patient)

  return HttpResponse()

#from django.shortcuts import render
from django.http import HttpResponse, Http404, HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST
from sigfox_messages import models, constants
from datetime import datetime
import struct

datetime_obj = datetime.now()
rtc = datetime_obj.strftime("%H:%M:%S")  # hh:mm:ss format
date = datetime_obj.strftime("%d/%m/%Y") # dd/mm/yy format


def get_attr_name(range_id):
  if range_id == 0:
    return "lower_range"
  elif range_id == 1:
    return "second_range"
  elif range_id == 2:
    return "third_range"
  elif range_id == 3:
    return "higher_range"


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


def update_bio(biometrics_24, dev_hist, attr, attr_value):

  # bpm range and some temperature related attributes are set directly
  if ("range" in attr):
    range_sum_field = attr + "_sum"
    setattr(biometrics_24, range_sum_field, attr_value + int(getattr(biometrics_24, range_sum_field)))
    setattr(biometrics_24, attr, int(getattr(biometrics_24, range_sum_field))/dev_hist.uplink_count)
  elif ("temp" == attr):
    biometrics_24.last_temp = attr_value
    biometrics_24.sum_temp = float(biometrics_24.sum_temp) + attr_value
    biometrics_24.avg_temp = round((float(biometrics_24.sum_temp)/dev_hist.uplink_count), 3)

    if (dev_hist.uplink_count > 1):
      if (attr_value < float(biometrics_24.min_temp)):
        biometrics_24.min_temp = attr_value
      elif (attr_value > float(biometrics_24.max_temp)):
        biometrics_24.max_temp = attr_value
    else:
      biometrics_24.min_temp = attr_value
      biometrics_24.max_temp = attr_value
  elif (dev_hist.uplink_count > 1):
    if ((attr == "max_bpm") and (attr_value > int(biometrics_24.max_bpm))):
      biometrics_24.max_bpm = str(attr_value)
    elif ((attr == "min_bpm") and (attr_value < int(biometrics_24.min_bpm))):
      biometrics_24.min_bpm = str(attr_value)
    elif ((attr == "max_ibi") and (attr_value > int(biometrics_24.max_ibi))):
      biometrics_24.max_ibi = str(attr_value)
    elif ((attr == "min_ibi") and (attr_value < int(biometrics_24.min_ibi))):
      biometrics_24.min_ibi = str(attr_value)
    elif ((attr == "avg_bpm") or (attr == "avg_ibi")):
      # Since we are on the same date, we can use date var to create datetime_obj2
      datetime_obj2 = datetime(int(date[6:]), int(date[3:5]), int(date[:2]), int(dev_hist.last_msg_time[:2]), int(dev_hist.last_msg_time[3:5]), int(dev_hist.last_msg_time[6:]))
      dojb = datetime_obj - datetime_obj2
      if (dobj.seconds <= constants.MAX_TIME_DELAY):
        sum_field = "sum_" + attr[4:]
        time_field = attr[4:] + "_time"
        partial_sum = attr_value * (dobj.seconds * 500) # 500 samples per second
        setattr(biometrics_24, sum_field, str(int(getattr(biometrics_24, sum_field)) + partial_sum))
        setattr(biometrics_24, time_field, str(int(getattr(biometrics_24, time_field)) + dobj.seconds))
        setattr(biometrics_24, attr, str(round(int(getattr(biometrics_24, sum_field))/(int(getattr(biometrics_24, time_field)) * 500))))
      else:
        pass # Lack of continuity upon message delivery. Leave avg_bpm/avg_ibi without updating
  else:
    # First message of the day
    setattr(biometrics_24, attr, attr_value)

    if ((attr == "avg_bpm") or (attr == "avg_ibi")):
      sum_field = "sum_" + attr[4:]
      time_field = attr[4:] + "_time"

      if (shipment_policy == constants.REGULAR_SHIP_POLICY):
        setattr(biometrics_24, sum_field, str(attr_value * 630 * 500))
        setattr(biometrics_24, time_field, str(630)) # regular shipment interval in seconds
      elif (shipment_policy == constants.RECOVERY_SHIP_POLICY):
        # Former day passed in the midst of a RECOVERY_SHIP_POLICY
        dobj = datetime.date(int(date[:2]), int(date[3:5]), int(date[6:]))
        d = datetime.timedelta(1) # Get time of yesterday's last message
        dobj = dobj - d
        date = dobj.strftime("%d/%m/%Y")
        try:
          dev_hist = models.Device_History.objects.filter(dev_conf=dev_hist.dev_conf, date=date)
          datetime_obj2 = datetime(int(date[6:]), int(date[3:5]), int(date[:2]), int(dev_hist.last_msg_time[:2]), int(dev_hist.last_msg_time[3:5]), int(dev_hist.last_msg_time[6:]))
          dobj = datetime_obj - datetime_obj2
          if (dobj.seconds <= constants.MAX_TIME_DELAY):
            setattr(biometrics_24, sum_field, str(attr_value * dobj.seconds * 500))
            setattr(biometrics_24, time_field, str(dobj.seconds))
        except models.Device_History.DoesNotExist:
          pass
      else: # EMERGENCY_SHIP_POLICY
        # We don't have a way to determine how much time the device has been gathering samples since it booted up. We know 'x' falls within 0<x<=10'30", 
        # range, but we don't know it accurately, so we start measuring device's computing time from the second message onwards to update the 
        # average(s).
        pass
  

@require_GET
def downlink(request, dev_id):

  try:
    dev_conf = models.Device_Config.objects.get(dev_id=dev_id)
  except models.Device_Config.DoesNotExist:
    output = "Device with device id " + dev_id + " does not exist"
    raise Http404(output)

  try:
    dev_hist = models.Device_History.objects.filter(dev_conf=dev_conf, date=date)
  except models.Device_History.DoesNotExist: # Create new history for dev_conf.dev_id device
    dev_hist = models.Device_History(dev_conf=dev_conf, date=date, running_since=rtc,
                                                    uplink_count=0, downlink_count=0)

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


@require_POST
def uplink(request):

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
    dev_hist = models.Device_History.objects.get(dev_conf=dev_conf, date=date) # Should return a single instance or nothing (exception)
    if (int(dev_hist.uplink_count) == 0):
      qs = models.Device_History.objects.filter(dev_conf=dev_conf).order_by("-date")
      if (len(qs) > 1):
        migrate_bio = 1
        last_date = qs[1].date # Get the latest date when an uplink message was sent prior to this one
  except models.Device_History.DoesNotExist:
    new_hist = 1 # Create a new history entry for the device
    try:
      d = models.Device_History.objects.filter(dev_conf=dev_conf).latest("date")
      last_date = d.date
      migrate_bio = 1
    except models.Device_History.DoesNotExist:
      pass # No messages stored from this device. This is the first one

    dev_hist = models.Device_History(dev_conf=dev_conf, date=date, running_since=rtc, last_msg_time=rtc,
                                                    uplink_count=0, downlink_count=0)

  # Update uplink_count 
  dev_hist.uplink_count = str(int(dev_hist.uplink_count) + 1)

  try:
    biometrics_24 = models.Biometrics_24.objects.get(patient=patient)
  except Biometrics_24.DoesNotExist:
    migrate_bio = 0
    biometrics_24 = models.Biometrics_24(patient=patient)

  if migrate_bio: # Migrate data on Biometrics_24 to Biometrics
    models.Biometrics.objects.create(patient=patient, date=last_date, avg_bpm=biometrics_24.avg_bpm, avg_ibi=biometrics_24.avg_ibi, 
                                     max_bpm=biometrics_24.max_bpm, max_ibi=biometrics_24.max_ibi, min_bpm=biometrics_24.min_bpm,
                                     min_ibi=biometrics_24.min_ibi, lower_range=biometrics_24.lower_range, second_range=biometrics_24.second_range,
                                     third_range=biometrics_24.third_range, higher_range=biometrics_24.higher_range, 
                                     last_temp=biometrics_24.last_temp, avg_temp=biometrics_24.avg_temp, max_temp=biometrics_24.max_temp,
                                     min_temp=biometrics_24.min_temp, last_alarm_time=biometrics_24.last_alarm_time,
                                     last_limit_time=biometrics_24.last_limit_time, last_elimit_time=biometrics_24.last_elimit_time)
    # Following payload data will "reset" Biometrics_24 (first payload to write on it)
    biometrics_24 = models.Biometrics_24(patient=patient) # new entry

  # Process the payload, update related fields on tables (following Uplink Payload Formats are defined in Readme.md)
  bin_data = bin(int(data, 16))[2:]

  if (len(bin_data) <= 80):
    bin_data = bin_data.zfill(80) # 10-byte packet
  else:
    bin_data = bin_data.zfill(96) # 12-byte packet

  # First 6 fields are common to all payload formats

  emergency = retrieve_field(bin_data, 0, 1)                   # emergency field
  ereason = retrieve_field(bin_data, 1, 1)                     # emergency reason field
  shipment_policy = retrieve_field(bin_data, 2, 2)             # shipment_policy field
  msg_type = retrieve_field(bin_data, 4, 3)                    # msg_type field

  if (msg_type==constants.ALARM_MSG):
    biometrics_24.last_alarm_time = rtc
  elif (msg_type==constants.LIMITS_MSG):
    biometrics_24.last_limit_time = rtc
  elif (msg_type==constants.ALARM_LIMITS_MSG):
    biometrics_24.last_alarm_time = rtc
    biometrics_24.last_limit_time = rtc


  # Retrieve format bits from rpv field
  payload_format = bin_data[10] + bin_data[21] + bin_data[32]  # payload format
  payload_format = int(payload_format, 2)

  if (payload_format != 4): # Retrieve range ids and percentages
    l = []
    ibit = 7
    per_sum = 0
    counter = 0
    while (counter != 3):
      range_id = retrieve_field(bin_data, ibit, 3)
      percentage = retrieve_field(bin_data, ibit+4, 7)
      range_name = get_attr_name(range_id)
      update_bio(biometrics_24, dev_hist, range_name, percentage)
      l.append(range_id)
      per_sum += percentage
      ibit += 11
      counter += 1

    z = [0, 1, 2, 3]
    for r_id in z:
      if r_id not in l:
        excluded_id = r_id
        break

    excluded_percentage = (100 - per_sum)
    range_name = get_attr_name(excluded_id)
    update_bio(biometrics_24, dev_hist, range_name, excluded_percentage)

    avg_bpm = retrieve_field(bin_data, 40, 8)                    # Average Beats Per Minute
    update_bio(biometrics_24, dev_hist, "avg_bpm", avg_bpm)


  # Next fields vary depending on which payload_format we're dealing with

  if (payload_format==0 or payload_format==1 or payload_format==5):
    max_bpm = retrieve_field(bin_data, 48, 8)                  # Highest record of Beats Per Minute
    min_bpm = retrieve_field(bin_data, 56, 8)                  # Lowest record of Beats Per Minute
    update_bio(biometrics_24, dev_hist, "max_bpm", max_bpm)
    update_bio(biometrics_24, dev_hist, "min_bpm", min_bpm)

    if ((max_bpm > dev_conf.higher_ebpm_limit) or (min_bpm < dev_conf.lower_ebpm_limit)):
      biometrics_24.last_elimit_time = rtc

  if (payload_format==0 or payload_format==2 or payload_format==4):
    if payload_format == 4: # 10 byte packet
      temp = retrieve_temp(bin_data, 48, 32)                    # Retrieve Temperature
    else:
      temp = retrieve_temp(bin_data, 64, 32)
    update_bio(biometrics_24, dev_hist, "temp", temp)

  if (payload_format==2 or payload_format==3 or payload_format==6):
    avg_ibi = retrieve_field(bin_data, 48, 16)                 # Average InterBeat Interval
    update_bio(biometrics_24, dev_hist, "avg_ibi", avg_ibi)

  if (payload_format==1 or payload_format==3 or payload_format==5 or payload_format==6):
    max_ibi = retrieve_field(bin_data, 64, 16)                 # Highest record of Interbeat interval
    min_ibi = retrieve_field(bin_data, 80, 16)                 # Lowest record of Interbeat interval
    update_bio(biometrics_24, dev_hist, "max_ibi", max_ibi)
    update_bio(biometrics_24, dev_hist, "min_ibi", min_ibi)

  if (payload_format == 7):
    elapsed_ms = retrieve_field(bin_data, 64, 32)              # Elapsed milliseconds since the recovery message was stored


  # Update dev_hist fields
  dev_hist.last_msg_time = rtc
  dev_hist.last_dev_state = "Functional"
  if (msg_type == constants.ERROR_MSG):
    if (payload_format == 4):
      dev_hist.last_dev_state = "Pulse sensor error"
    else:
      dev_hist.last_dev_state = "Temperature sensor error"

  # if emergency:
      # check emergency already exists on database
      # if not, create emergency on database, add data to database (Emergency_Biometrics), create attention request
        # Initiate calling to SMS and Whatssap Systems (background process), do not rely on requests to the Monitor service (uplink view to be executed)
      # else (ongoing emergency)
        # Merge payload data with Emergency_Biometrics
        # When emergency ends (device perspective), emergency field equals to 0. i.e next payload will be added to basic Biometrics tables, not to Emergency_Biometrics
        # Emergency will continue active until someone marks it as attended accessing a URL, or from the web

  try:
    latitude, longitude = request.POST["geolocation"]
    # location = google_maps call (i.e "Calle San Juan, Zamora") // Consultar que posibilidades ofrece el API
    # No llamar al API cada vez que recibes un mensaje (demasiadas llamadas). Hacerlo bien cuando cambien las coordenadas(implica almacenar coordenadas y comparar # las recibidas con las almacenadas) o consultar cada cierto tiempo (1 vez cada 20 minutos en condiciones normales y una cada 5' en emergencias, por ejemplo)
    dev_hist.last_known_location = location
  except KeyError:
    latitude, longitude = (-1, -1)

  dev_hist.save()
  biometrics_24.save()
  if new_hist:
    models.Patient_Device_History.objects.create(dev_hist=dev_hist, patient=patient)

  return HttpResponse()

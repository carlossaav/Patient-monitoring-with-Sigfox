from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.http import HttpResponseRedirect, HttpResponse, Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from http import HTTPStatus
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from sigfox_messages import utils, models, constants
from sigfox_messages.bot import manager
from multiprocessing import Process
import asyncio, datetime, json
from django.utils import timezone

@require_GET
@csrf_exempt
def downlink(request, dev_id):

  datetime_obj = timezone.make_aware(datetime.datetime.now())
  date = datetime_obj.date()
  rtc = datetime_obj.strftime("%H:%M:%S")

  try:
    dev_conf = models.Device_Config.objects.get(dev_id=dev_id)
  except models.Device_Config.DoesNotExist:
    output = "Device with device id " + dev_id + " does not exist"
    raise Http404(output)

  try:
    dev_hist = models.Device_History.objects.get(dev_conf=dev_conf, date=date)
  except models.Device_History.DoesNotExist:
    # Create new history for dev_conf.dev_id device
    dev_hist = models.Device_History(dev_conf=dev_conf, date=date,
                                     running_since=datetime_obj,
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


@require_POST
@csrf_exempt
def uplink(request):

  datetime_obj = timezone.make_aware(datetime.datetime.now())
  date = datetime_obj.date()

  try:
    print()
    print("(uplink) request.body =", request.body)
    body = json.loads(request.body)
    # print("body = json.loads(request.body)")
    # print("(uplink) body =", body)
    # print("(uplink) type(body) =", type(body))

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
        # Get the latest date when an uplink message was sent (prior to this one)
        last_date = qs[1].date
  except models.Device_History.DoesNotExist:
    new_hist = 1 # Create a new history entry for the device
    try:
      d = models.Device_History.objects.filter(dev_conf=dev_conf).latest("date")
      last_date = d.date
      migrate_bio = 1
    except models.Device_History.DoesNotExist:
      pass # No messages stored from this device. This is the first one

    dev_hist = models.Device_History(dev_conf=dev_conf, date=date,
                                     running_since=datetime_obj,
                                     last_msg_time=datetime_obj,
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
    print(f"last_date = {last_date}, flush=True")
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
  emergency = utils.retrieve_field(bin_data, 0, 1)                   # emergency field
  print(f"(uplink) emergency = {emergency}")
  ereason_payload = utils.retrieve_field(bin_data, 1, 1)             # emergency reason field
  print(f"(uplink) ereason = {ereason_payload}")
  shipment_policy = utils.retrieve_field(bin_data, 2, 2)             # shipment_policy field
  print(f"(uplink) shipment_policy = {shipment_policy}")
  msg_type = utils.retrieve_field(bin_data, 4, 3)                    # msg_type field
  print(f"(uplink) msg_type = {msg_type}")

  new_e = 0
  emerg_update = 0
  if emergency:
    emerg_update = 1
  try:
    ebio = models.Emergency_Biometrics.objects.filter(patient=patient).latest("emerg_timestamp")
    if emergency:
      # check emergency creation/reactivation
      datetime_obj2 = ebio.emerg_timestamp
      seconds = utils.get_sec_diff(datetime_obj, datetime_obj2)
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
      # location = google_maps API call?? (i.e "Calle San Juan, Zamora") # Check out Google Maps API possibilities
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
    from sigfox_messages.bot import wait_emergency

    ebio = models.Emergency_Biometrics(patient=patient,
                                       emerg_timestamp=datetime_obj,
                                       emsg_count="0",
                                       active="Yes")
    att_req = models.Attention_request(emergency=ebio,
                                       patient=patient,
                                       doctor=patient.doctor,
                                       request_timestamp=datetime_obj,
                                       request_priority="Urgent",
                                       status="Unattended")
    emerg_event = wait_emergency[patient.dni]
    if (emerg_event.is_set()):
      emerg_event.clear()
    p = Process(target=utils.notifier, args=(patient, ))
    p.start()


  if emergency:
    ebio.emsg_count = str(int(ebio.emsg_count) + 1)

  # Update biometrics timestamps
  if (msg_type == constants.ALARM_MSG):
    biometrics_24.last_alarm_time = datetime_obj
  elif (msg_type == constants.LIMITS_MSG):
    biometrics_24.last_limit_time = datetime_obj
  elif (msg_type == constants.ALARM_LIMITS_MSG):
    biometrics_24.last_alarm_time = datetime_obj
    biometrics_24.last_limit_time = datetime_obj

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
      range_id = utils.retrieve_field(bin_data, ibit, 3)
      print(f"(uplink) range_id = {range_id}")
      percentage = utils.retrieve_field(bin_data, ibit+4, 7)
      print(f"(uplink) percentage = {percentage}")
      range_name = utils.get_attr_name(range_id)
      utils.update_ranges(dev_hist, range_name, percentage, biometrics_24, None)
      if emergency:
        utils.update_ranges(dev_hist, range_name, percentage, None, ebio)
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
    range_name = utils.get_attr_name(excluded_id)
    print(f"(uplink) range_name = {range_name}")
    excluded_percentage = (100 - per_sum)
    print(f"(uplink) excluded_percentage = {excluded_percentage}")
    utils.update_ranges(dev_hist, range_name, excluded_percentage, biometrics_24, None)
    if emergency:
      utils.update_ranges(dev_hist, range_name, excluded_percentage, None, ebio)

    if (excluded_id in range(4)):
      p[excluded_id] = excluded_percentage

    lower_range = p[0]
    second_range = p[1]
    third_range = p[2]
    higher_range = p[3]

    avg_bpm = utils.retrieve_field(bin_data, 40, 8)                    # Average Beats Per Minute
    print(f"(uplink) avg_bpm = {avg_bpm}")
    utils.update_bpm_ibi(dev_hist, "avg_bpm", avg_bpm, biometrics_24, None,
                         datetime_obj, shipment_policy)
    if emergency:
      utils.update_bpm_ibi(dev_hist, "avg_bpm", avg_bpm, None, ebio,
                           datetime_obj, shipment_policy)

  # Next fields vary depending on which payload_format we're dealing with

  if (payload_format==0 or payload_format==1 or payload_format==5):
    max_bpm = utils.retrieve_field(bin_data, 48, 8)                  # Highest record of Beats Per Minute
    print(f"(uplink) max_bpm = {max_bpm}")
    min_bpm = utils.retrieve_field(bin_data, 56, 8)                  # Lowest record of Beats Per Minute
    print(f"(uplink) min_bpm = {min_bpm}")
    utils.update_bpm_ibi(dev_hist, "max_bpm", max_bpm, biometrics_24, None)
    utils.update_bpm_ibi(dev_hist, "min_bpm", min_bpm, biometrics_24, None)
    if emergency:
      utils.update_bpm_ibi(dev_hist, "max_bpm", max_bpm, None, ebio)
      utils.update_bpm_ibi(dev_hist, "min_bpm", min_bpm, None, ebio)

    if ((max_bpm > int(dev_conf.higher_ebpm_limit)) or
        (min_bpm < int(dev_conf.lower_ebpm_limit))):
      biometrics_24.last_elimit_time = datetime_obj

  if (payload_format==0 or payload_format==2 or payload_format==4):
    if payload_format == 4: # 10 byte packet
      temp = utils.retrieve_temp(bin_data, 48, 32)                    # Retrieve Temperature
      print(f"(uplink) temp = {temp}")
    else:
      temp = utils.retrieve_temp(bin_data, 64, 32)
      print(f"(uplink) temp = {temp}")
    utils.update_temp(dev_hist, temp, biometrics_24, None)
    if emergency:
      utils.update_temp(dev_hist, temp, None, ebio)

  if (payload_format==2 or payload_format==3 or payload_format==6):
    avg_ibi = utils.retrieve_field(bin_data, 48, 16)                 # Average InterBeat Interval
    print(f"(uplink) avg_ibi = {avg_ibi}")
    utils.update_bpm_ibi(dev_hist, "avg_ibi", avg_ibi, biometrics_24, None,
                         datetime_obj, shipment_policy)
    if emergency:
      utils.update_bpm_ibi(dev_hist, "avg_ibi", avg_ibi, None, ebio,
                           datetime_obj, shipment_policy)

  if (payload_format==1 or payload_format==3 or
      payload_format==5 or payload_format==6):
    max_ibi = utils.retrieve_field(bin_data, 64, 16)                 # Highest record of Interbeat interval
    print(f"(uplink) max_ibi = {max_ibi}")
    min_ibi = utils.retrieve_field(bin_data, 80, 16)                 # Lowest record of Interbeat interval
    print(f"(uplink) min_ibi = {min_ibi}")
    utils.update_bpm_ibi(dev_hist, "max_ibi", max_ibi, biometrics_24, None)
    utils.update_bpm_ibi(dev_hist, "min_ibi", min_ibi, biometrics_24, None)
    if emergency:
      utils.update_bpm_ibi(dev_hist, "max_ibi", max_ibi, None, ebio)
      utils.update_bpm_ibi(dev_hist, "min_ibi", min_ibi, None, ebio)

  if (payload_format == 7):
    elapsed_ms = utils.retrieve_field(bin_data, 64, 32)              # Elapsed milliseconds since the recovery message was stored
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
  dev_hist.last_msg_time = datetime_obj
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
    emerg_event.set() # att_req, ebio and epayload saved to DB. Set event
  if new_hist:
    models.Patient_Device_History.objects.create(dev_hist=dev_hist, patient=patient)

  return HttpResponse(status=HTTPStatus.NO_CONTENT)



def register(request):
  
  # Process/show registration form
  if (request.method == 'POST'):
    form = UserCreationForm(request.POST)
    if form.is_valid():
      new_user = form.save()
      return HttpResponseRedirect("/sigfox_messages/")
  else:
    form = UserCreationForm()

  return render(request, "registration/register.html", {'form': form})


# @csrf_exempt
def index(request):

  context = {}
  if (request.user.is_authenticated):
    err = 0
    if (request.user.is_staff):
      emerg_qs = models.Emergency_Biometrics.objects.filter(active="Yes")
      if (emerg_qs.exists()):
        context["emergency_list"] = emerg_qs

      if (request.method == "POST"):
        err, output = utils.ensure_params_presence(request.POST)
        if not err:
          if ("doctor name" in request.POST): # Add a new doctor to Database
            name = request.POST['doctor name']
            surname = request.POST['doctor surname']
            state = request.POST['doctor state']
            qs = models.Doctor.objects.filter(name=name, surname=surname)
            if (qs.exists()):
              err = 1
              output = "There's an existent doctor with that name on database. Registration failed"
            else:
              doctor = models.Doctor(name=name, surname=surname, state=state)
              doctor.save()
              context["doctor_registered"] = 1
          elif ("dev id" in request.POST): # Add a new device to Database
            dev_id = request.POST['dev id']
            higher_bpm_limit = request.POST['higher bpm limit']
            lower_bpm_limit = request.POST['lower bpm limit']
            higher_ebpm_limit = request.POST['higher ebpm limit']
            lower_ebpm_limit = request.POST['lower ebpm limit']
            bpm_limit_window = request.POST['bpm limit window']
            min_delay = request.POST['min delay']
            dev_conf = models.Device_Config(dev_id=dev_id,
                                            higher_bpm_limit=higher_bpm_limit,
                                            lower_bpm_limit=lower_bpm_limit,
                                            higher_ebpm_limit=higher_ebpm_limit,
                                            lower_ebpm_limit=lower_ebpm_limit,
                                            bpm_limit_window=bpm_limit_window,
                                            min_delay=min_delay)
            dev_conf.save()
            context["device_registered"] = 1
          elif ("patient dni" in request.POST): # Add a new patient to Database
            l = request.POST['patient doctor'].split()
            dname = l[0]
            dsurname = ' '.join(l[1:])
            try: # Check out that doctor's presence
              doctor = models.Doctor.objects.get(name=dname, surname=dsurname)
            except models.Doctor.DoesNotExist:
              output = "Doctor with name '" + request.POST['patient doctor']
              output += "' has not been found in our Database.\nYou must first register such "
              output += "doctor before adding its new patient."
              print(output)
              return render(request, "sigfox_messages/index.html", context={"error_message": output})

            # Let's check if there's any patient registered on DB with such dni
            dni = request.POST['patient dni']
            qs = models.Patient.objects.filter(dni=dni)
            if (qs.exists()):
              err = 1
              output = "There's another patient on DB with dni '" + dni + "'. Registration failed"
            else:
              # Check if the device with the id provided has already been registered on database.
              qs = models.Device_Config.objects.filter(dev_id=request.POST['patient device id'])
              if (qs.exists()):
                # There must be only one element on the QuerySet, (primary key contraint)
                dev_conf = qs.get()
                # Is this device already linked to any patient?
                qs = models.Patient.objects.filter(dev_conf=dev_conf)
                if (qs.exists()):
                  err = 1
                  output = "There's another patient currently linked to that device."
                  output += " Registration failed"
                else: # expected behaviour
                  name = request.POST['patient name']
                  surname = request.POST['patient surname']
                  age = request.POST['patient age']
                  follow_up = request.POST['patient follow-up']

                  patient = models.Patient(dni=dni, name=name, surname=surname, age=age,
                                           user=None, doctor=doctor, dev_conf=dev_conf,
                                           follow_up=follow_up)
                  patient.save()
                  context["patient_registered"] = 1
                  
                  from sigfox_messages.bot import wait_emergency
                  wait_emergency[patient.dni] = manager.Event()
              else:
                err = 1
                output = "Device with device id '" + request.POST['patient device id']
                output += "' has not been found in our Database.\nYou must first register a new "
                output += " device with such device identifier before adding a new patient."
    else:
      emergency_list = []
      doctors_qs = models.Doctor.objects.filter(state="available")
      patients_qs = models.Patient.objects.filter(user=request.user)
      for patient in patients_qs:
        try:
          ebio = models.Emergency_Biometrics.objects.filter(patient=patient).latest("emerg_timestamp")
          if (ebio.active == "Yes"):
            emergency_list.append(ebio)
        except models.Emergency_Biometrics.DoesNotExist:
          pass

      if (doctors_qs.exists()):
        context["doctors_list"] = doctors_qs
      if (patients_qs.exists()):
        context["patients_list"] = patients_qs
        if (emergency_list != []):
          context["emergency_list"] = emergency_list

      if (request.method == "POST"): # Regular user trying to link its account with some existent patient
        err, output = utils.ensure_params_presence(request.POST)
        if not err:
          try:
            patient = models.Patient.objects.get(dni=request.POST["patient dni"])
            # print(f"patient linked to {patient.user}")
            if (patient.user == None):
              patient.user = request.user
              # print(f"linking patient to {request.user}")
              patient.save()
              context["patient_linked"] = 1
            elif (patient.user == request.user):
              err = 1
              output = "You are already following up on that patient."
            else:
              err = 1
              output = "That patient is already linked to another account. Log in with "
              output += "that account to see that patient's information."
          except models.Patient.DoesNotExist:
            err = 1
            output = "No patient has been found with the dni provided."

    if err:
      context["error_message"] = output
      print(output)

  return render(request, "sigfox_messages/index.html", context=context)


@require_GET
def emergency_lookup(request):

  context = {}
  if (request.user.is_authenticated and
      request.user.is_staff):
    emerg_qs = models.Emergency_Biometrics.objects.all()
    if (emerg_qs.exists()):
      context["emergency_list"] = emerg_qs

  return render(request, "sigfox_messages/emergency_lookup.html", context=context)


@require_GET
def patient_lookup(request):

  context = {}
  if (request.user.is_authenticated and
      request.user.is_staff):
    patient_list = models.Patient.objects.all()
    if (patient_list.exists()):
      context["patient_list"] = patient_list

  return render(request, "sigfox_messages/patient_lookup.html", context=context)


def patient_detail(request, patient_id):

  context = {}
  if (request.user.is_authenticated):
    try:
      patient = models.Patient.objects.get(dni=patient_id)
      if ((not request.user.is_staff) and (request.user != patient.user)):
        return render(request, "sigfox_messages/patient_detail.html",
                      context={"not_allowed": 1})
      pcontacts = models.Patient_Contact.objects.filter(patient=patient)
      contact_list = []
      for pcontact in pcontacts:
        contact_list.append(pcontact.contact.phone_number)
      context["phone_numbers"] = contact_list
      context["bio_24"] = models.Biometrics_24.objects.get(patient=patient)
    except models.Patient.DoesNotExist:
      return render(request, "sigfox_messages/patient_detail.html",
                    context={"patient_id": patient_id})
    except models.Biometrics_24.DoesNotExist:
      pass

    try:
      ebio = models.Emergency_Biometrics.objects.filter(patient=patient).latest("emerg_timestamp")
      # print(f"emergency timestamp = {ebio.emerg_timestamp}")
      if (ebio.active == "Yes"):
        context["ongoing_emergency"] = ebio

      att_req = models.Attention_request.objects.get(emergency=ebio)
      if ((request.method == "GET") and
          ("emergency_attended" in request.GET) and
          (request.GET["emergency_attended"] == "true")):
        att_req.status = "Attended"
        att_req.save()

      if (ebio.active == "Yes"):
        if (att_req.status == "Attended"):
          context["attended"] = 1
        else:
          context["not_attended"] = 1
    except models.Emergency_Biometrics.DoesNotExist:
      pass
    except models.Attention_request.DoesNotExist:
      pass

    emergency_list = models.Emergency_Biometrics.objects.filter(patient=patient)
    bio_list = models.Biometrics.objects.filter(patient=patient)
    if (emergency_list.exists()):
      context["emergency_list"] = emergency_list
    if (bio_list.exists()):
      context["bio_list"] = bio_list

    att_req_qs = models.Attention_request.objects.filter(patient=patient)
    if (not att_req_qs.exists()): # Empty att_req_qs QuerySet
      context["empty_att_req"] = 1
    else:
      auto_att_req = []
      manual_att_req = []
      for att_req in att_req_qs:
        if (att_req.emergency != None):
          auto_att_req.append(att_req)
        else:
          manual_att_req.append(att_req)

      if (manual_att_req != []):
        context["manual_att_req"] = manual_att_req
      if (auto_att_req != []):
        context["auto_att_req"] = auto_att_req

    if ((request.method == "GET")
        and ("unlink_acc" in request.GET)
        and (request.GET["unlink_acc"] == "true")
        and (patient.user != None)):
      patient.user = None
      patient.save()
      context["unlink"] = 1
    elif (request.method == "POST" and request.user.is_staff):
      perr = 0
      params = ["doctor full name", "device id", "follow up"]
      for p in params:
        if (p not in request.POST):
          perr = 1
          break
      
      if perr:
        context["form_err"] = 1
      else:
        invalid_field = 0
        update = 0
        if (request.POST["doctor full name"] != ""):
          l = request.POST['doctor full name'].split()
          dname = l[0]
          dsurname = ' '.join(l[1:])
          try: # Check out that doctor's presence
            doctor = models.Doctor.objects.get(name=dname, surname=dsurname)
            patient.doctor = doctor
            update = 1
          except models.Doctor.DoesNotExist:
            invalid_field = 1
            output = "Doctor with name '" + request.POST['doctor full name']
            output += "' has not been found in our Database."

        if (request.POST["device id"] != ""):
          try:
            dev_conf = models.Device_Config.objects.get(dev_id=request.POST["device id"])
            pat_qs = models.Patient.objects.filter(dev_conf=dev_conf)
            if (pat_qs.exists()):
              invalid_field = 1 # There's another patient linked to that device
              output = "Device with identifier '" + request.POST["device id"]
              output += "' is already in use."
            else:
              patient.dev_conf = dev_conf
              update = 1
          except models.Device_Config.DoesNotExist:
            invalid_field = 1
            output = "Device with device identifier '" + request.POST['device id']
            output += "' has not been found in our Database."

        follow_up = request.POST["follow up"]
        if (follow_up != ""):
          if ((follow_up == "critical") or (follow_up == "normal")):
            patient.follow_up = follow_up
            update = 1
          else:
            invalid_field = 1
            output = "Supported values for follow-up are 'normal' or 'critical'"

        if invalid_field:
          print(output)
          context["error_message"] = output
        if update:
          print("Updating patient fields")
          patient.save()
          if not invalid_field: # All specified fields were successfully updated
            context["patient_updated"] = 1

    context["patient"] = patient

  return render(request, "sigfox_messages/patient_detail.html", context=context)


@require_GET
def doctor_lookup(request):

  context = {}
  if (request.user.is_authenticated and
      request.user.is_staff):
    doctor_list = models.Doctor.objects.all()
    if (doctor_list.exists()):
      context["doctor_list"] = doctor_list

  return render(request, "sigfox_messages/doctor_lookup.html", context=context)


def doctor_detail(request, doctor_id):

  datetime_obj = timezone.make_aware(datetime.datetime.now())
  context = {}

  if (request.user.is_authenticated):
    try:
      doctor = models.Doctor.objects.get(id=doctor_id)
      context["doctor"] = doctor
    except models.Doctor.DoesNotExist:
      return render (request, "sigfox_messages/doctor_detail.html", context=context)

    if (request.user.is_staff):
      att_req_qs = models.Attention_request.objects.filter(doctor=doctor,
                                                           status="Unattended")
      if (att_req_qs.exists()):
        context["att_req_qs"] = att_req_qs

      if (request.method == "POST" and
          "doctor state" in request.POST):
        if (request.POST["doctor state"] == "busy" or
            request.POST["doctor state"] == "available"):
          doctor.state = request.POST["doctor state"]
          doctor.save()
          context["doctor_updated"] = 1
        else:
          context["wrong_state"] = request.POST["doctor state"]
    elif (request.method == "POST" and
          ("request priority" in request.POST) and
          ("patient dni" in request.POST)):
      if (request.POST["request priority"] == "Normal" or
          request.POST["request priority"] == "Urgent"):
        try:
          invalid_patient = 0
          patient = models.Patient.objects.get(dni=request.POST["patient dni"])
          patient_qs = models.Patient.objects.filter(user=request.user)
          if ((patient_qs.exists()) and
              (patient in patient_qs)):
            if (doctor.state == "available"):
              att_req_qs = models.Attention_request.objects.filter(emergency=None,
                                                                   patient=patient,
                                                                   status="Unattended")
              if (not att_req_qs.exists()):
                models.Attention_request.objects.create(emergency=None,
                                                        patient=patient,
                                                        doctor=doctor,
                                                        request_timestamp=datetime_obj,
                                                        request_priority=request.POST["request priority"],
                                                        status="Unattended")
                context["att_req_created"] = 1
              else:
                context["already_assigned"] = 1
            else:
              context["not_available"] = 1
          else:
            invalid_patient = 1
        except models.Patient.DoesNotExist:
          invalid_patient = 1

        if invalid_patient:
          context["invalid_patient"] = 1
      else:
        context["invalid_priority"] = 1

  return render (request, "sigfox_messages/doctor_detail.html", context=context)


@require_GET
def pdoctor_lookup(request, doctor_id):

  context = {}
  if (request.user.is_authenticated and
      request.user.is_staff):
    try:
      doctor = models.Doctor.objects.get(id=doctor_id)
      patient_qs = models.Patient.objects.filter(doctor=doctor)
      if (patient_qs.exists()):
        context["patient_qs"] = patient_qs
      context["doctor"] = doctor
    except models.Doctor.DoesNotExist:
      pass

  return render(request, "sigfox_messages/pdoctor_lookup.html", context=context)


@require_GET
def device_lookup(request):

  context = {}
  if (request.user.is_authenticated and
      request.user.is_staff):
    device_list = models.Device_Config.objects.all()
    if (device_list.exists()):
      context["device_list"] = device_list

  return render(request, "sigfox_messages/device_lookup.html", context=context)


@require_GET
def entity_lookup(request, entity_class, template):
  pass


def device_config_detail(request, device_id):

  context = {}
  if (request.user.is_authenticated):
    try:
      dev_conf = models.Device_Config.objects.get(dev_id=device_id)
      context["device"] = dev_conf
      patient = models.Patient.objects.get(dev_conf=dev_conf)
      context["patient"] = patient

      if ((not request.user.is_staff) and (request.user != patient.user)):
        return render(request, "sigfox_messages/device_config_detail.html",
                      context={"not_allowed": 1})

      qs_hist = models.Device_History.objects.filter(dev_conf=dev_conf)
      if (qs_hist.exists()): # There's at least one message registered from the device
        context["qs_hist"] = qs_hist
    except models.Device_Config.DoesNotExist:
      return render(request, "sigfox_messages/device_config_detail.html",
                    context={"device_id": device_id})
    except models.Patient.DoesNotExist:
      context["failed_patient"] = 1

    if (request.method == "POST" and request.user.is_staff):
      d = dict(request.POST)
      d.pop("csrfmiddlewaretoken")
      update = 0
      missing_field = 0
      # print(d)
      for attr in d:
        if (hasattr(dev_conf, attr)):
          if (d[attr] != ['']):
            try:
              value = int(d[attr][0])
              setattr(dev_conf, attr, str(value))
              update = 1
            except ValueError:
              missing_field = 1
        else:
          # print(f"attribute {attr} is not an attribute of a Device_Config object")
          missing_field = 1

      if missing_field: # Some fields could not be updated
        context["missing_field"] = 1
      if update:
        print("Updating fields")
        dev_conf.save()
        if not missing_field: # All specified fields were successfully updated
          context["device_updated"] = 1

  return render(request, "sigfox_messages/device_config_detail.html", context=context)


# device_config_id?date='x'/
@require_GET
def device_hist_detail(request, device_hist_id):

  context = {}
  try:
    dev_hist = models.Device_History.objects.get(id=device_hist_id)
    patient = models.Patient.objects.get(dev_conf=dev_hist.dev_conf)
    if ((not request.user.is_staff) and (request.user != patient.user)):
      context["not_allowed"] = 1
    else:
      context["dev_hist"] = dev_hist
  except models.Device_History.DoesNotExist:
    pass

  return render(request, "sigfox_messages/device_hist_detail.html", context=context)


# patient_id?date='x'/
@require_GET
def biometrics_detail(request, biometrics_id):

  context = {}
  try:
    bio = models.Biometrics.objects.get(id=biometrics_id)
    if ((not request.user.is_staff) and (request.user != bio.patient.user)):
      context["not_allowed"] = 1
    else:
      context["bio"] = bio
  except models.Biometrics.DoesNotExist:
    pass

  return render(request, "sigfox_messages/biometrics_detail.html", context=context)


@require_GET
def biometrics24_detail(request, patient_id):

  context = {}
  try:
    patient = models.Patient.objects.get(dni=patient_id)
    bio_24 = models.Biometrics_24.objects.get(patient=patient)
    if ((not request.user.is_staff) and (request.user != bio_24.patient.user)):
      context["not_allowed"] = 1
    else:
      context["bio"] = bio_24
      context["today"] = 1
  except models.Patient.DoesNotExist:
    pass
  except models.Biometrics_24.DoesNotExist:
    pass

  return render(request, "sigfox_messages/biometrics_detail.html", context=context)



@require_GET
def emergency_detail(request, emergency_id):

  context = {}
  try:
    emergency = models.Emergency_Biometrics.objects.get(id=emergency_id)
    if ((not request.user.is_staff) and
        (request.user != emergency.patient.user)):
      context["not_allowed"] = 1
    else:
      context["ebio"] = emergency
      epayload_qs = models.Emergency_Payload.objects.filter(emergency=emergency)
      if (epayload_qs.exists()):
        context["epayload_qs"] = epayload_qs
  except models.Emergency_Biometrics.DoesNotExist:
    pass

  return render(request, "sigfox_messages/emergency_detail.html", context=context)


@require_GET
def epayload_detail(request, epayload_id):
  
  context = {}
  try:
    epayload = models.Emergency_Payload.objects.get(id=epayload_id)
    if ((not request.user.is_staff) and
        (request.user != epayload.emergency.patient.user)):
      context["not_allowed"] = 1
    else:
      context["epayload"] = epayload
  except models.Emergency_Payload.DoesNotExist:
    pass

  return render(request, "sigfox_messages/epayload_detail.html", context=context)


@require_GET
def att_req_detail(request, att_req_id):

  context = {}
  try:
    att_req = models.Attention_request.objects.get(id=att_req_id)
    if ((not request.user.is_staff) and
        (request.user != att_req.patient.user)):
      return render(request, "sigfox_messages/attention_request_detail.html",
                    context={"not_allowed": 1})
    else:
      context["att_req"] = att_req
      if (att_req.emergency != None):
        context["associated_emergency"] = 1
  except models.Attention_request.DoesNotExist:
    att_req = None

  if (att_req != None):
    if ((request.method == "GET") and
        ("emergency_attended" in request.GET) and
        (request.GET["emergency_attended"] == "true")):
      att_req.status = "Attended"
      att_req.save()
    if (att_req.status == "Unattended"):
      context["not_attended"] = 1

  return render(request, "sigfox_messages/attention_request_detail.html",
                context=context)

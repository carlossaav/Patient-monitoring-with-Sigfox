from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.http import HttpResponseRedirect, HttpResponse, Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from http import HTTPStatus
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from sigfox_messages import utils, models, constants, forms
from multiprocessing import Process
import asyncio, json
from datetime import datetime, timedelta
from django.utils import timezone

@require_GET
@csrf_exempt
def downlink(request, dev_id):

  datetime_obj = timezone.now()
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
                                     last_msg_time=datetime_obj,
                                     last_dev_state="Functional",
                                     last_known_latitude="Unknown",
                                     last_known_longitude="Unknown",
                                     uplink_count=0, downlink_count=0,
                                     higher_bpm_limit=dev_conf.higher_bpm_limit,
                                     lower_bpm_limit=dev_conf.lower_bpm_limit,
                                     continuous_delivery=True)

  dev_hist.downlink_count += 1
  dev_hist.save()

  # Build payload following rtc:bt:msg:ub:lb:bx downlink payload format

  l = [int(rtc[:2]), int(rtc[3:5]), int(rtc[6:])]  # hour, minute and sec

  payload = ""
  payload += format(l[0], "05b")
  for e in l[1:]:
    payload += format(e, "06b")

  payload += format(dev_conf.bpm_limit_window, "07b")   # bt
  payload += format(dev_hist.uplink_count, "08b")       # msg  
  payload += format(dev_conf.higher_bpm_limit, "08b")   # ub
  payload += format(dev_conf.lower_bpm_limit, "08b")    # lb
  payload += format(dev_conf.min_delay, "016b")         # bx

  payload = hex(int(payload, 2))[2:] # Convert to hex string. Skip '0x' chars

  d = {dev_id: {"downlinkData": payload}}
  response = JsonResponse(d)
  print("(downlink) response.content = ", response.content)
  print("(downlink) response = ", response)
  return response


@require_POST
@csrf_exempt
def uplink(request):

  datetime_obj = timezone.now()
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

  migrate_bio = 0
  try:
    # Should return a single instance or nothing (exception)
    dev_hist = models.Device_History.objects.get(dev_conf=dev_conf, date=date)
    if (dev_hist.uplink_count == 0):
      qs = models.Device_History.objects.filter(dev_conf=dev_conf).order_by("-date")
      if (len(qs) > 1):
        # A downlink message was saved before reaching the uplink view
        # Get the latest date when an uplink message was sent (prior to this one) to migrate data
        # (qs[1]; qs[0] contains actual date -> due to downlink message saving)
        last_date = qs[1].date
        migrate_bio = 1
    else:
      delta = datetime_obj - dev_hist.last_msg_time
      if (delta.seconds > constants.MAX_TIME_DELAY):
        dev_hist.continuous_delivery = False
  except models.Device_History.DoesNotExist:
    try:
      d = models.Device_History.objects.filter(dev_conf=dev_conf).latest("date")
      last_date = d.date
      migrate_bio = 1
    except models.Device_History.DoesNotExist:
      pass # No messages stored from this device. This is the first one

    # Create a new history entry for the device
    dev_hist = models.Device_History(dev_conf=dev_conf, date=date,
                                     running_since=datetime_obj,
                                     last_msg_time=datetime_obj,
                                     last_dev_state="Functional",
                                     last_known_latitude="Unknown",
                                     last_known_longitude="Unknown",
                                     uplink_count=0, downlink_count=0,
                                     higher_bpm_limit=dev_conf.higher_bpm_limit,
                                     lower_bpm_limit=dev_conf.lower_bpm_limit,
                                     continuous_delivery=True)

  dev_hist.uplink_count += 1  # Update uplink_count

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
    ebio = models.Emergency_Biometrics.objects.filter(patient=patient).latest("spawn_timestamp")
    last_msg_time = models.Device_History.objects.filter(dev_conf=dev_conf).latest("date").last_msg_time
    if emergency:
      # check emergency creation/reactivation
      seconds = utils.get_sec_diff(datetime_obj, ebio.spawn_timestamp)
      if (seconds > constants.NEW_EMERG_DELAY):
        new_e = 1 # create a new one
        if (ebio.active): # Deactivate emergency
          ebio.active = False
          ebio.termination_timestamp = last_msg_time
          # 'ebio' will then hold the new emergency, update it (last emergency) on Database
          ebio.save()
      elif (not ebio.active): # Still on the same 'logical' emergency, reactivate it
        ebio.active = True
        ebio.termination_timestamp = None # Not ended yet
    elif (ebio.active): # emergency == 0 (Emergency finished)
      ebio.active = False
      ebio.termination_timestamp = last_msg_time
      emerg_update = 1
  except models.Emergency_Biometrics.DoesNotExist:
    if emergency:
      new_e = 1

  try:
    loc_info = body["computedLocation"]
    # print(f"loc_info = {loc_info}")
    if (loc_info["status"] == 1): # Geolocation successlly computed
      latitude = loc_info["lat"]
      longitude = loc_info["lng"]
      dev_hist.last_known_latitude = str(latitude)
      dev_hist.last_known_longitude = str(longitude)
  except KeyError:
    print("Geolocation not available")

  if new_e: # create new emergency, Attention request
    from sigfox_messages.bot import wait_emergency

    ebio = models.Emergency_Biometrics(patient=patient,
                                       spawn_timestamp=datetime_obj,
                                       emsg_count=0,
                                       active=True)
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
    ebio.emsg_count += 1

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

    if ((max_bpm > dev_conf.higher_ebpm_limit) or
        (min_bpm < dev_conf.lower_ebpm_limit)):
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
                                        avg_bpm=avg_bpm, avg_ibi=avg_ibi,
                                        max_bpm=max_bpm, max_ibi=max_ibi,
                                        min_bpm=min_bpm, min_ibi=min_ibi,
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

  return HttpResponse(status=HTTPStatus.NO_CONTENT)


def register(request):
  
  # Process/show registration form
  form = UserCreationForm()
  if (request.method == 'POST'):
    form = UserCreationForm(request.POST)
    if form.is_valid():
      form.save() # Add a new User
      return HttpResponseRedirect("/sigfox_messages/")

  return render(request, "registration/register.html", {'form': form})


# @csrf_exempt
def index(request):

  datetime_obj = timezone.now()
  context = {}
  if (request.user.is_authenticated):
    if (request.user.is_staff):
      emerg_qs = models.Emergency_Biometrics.objects.filter(active=True)
      if (emerg_qs.exists()):
        emergency_list = []
        for emergency in emerg_qs:
          if (emergency.active):
            emergency = utils.check_emergency_deactivation(emergency, datetime_obj)
            if (emergency.active): # Check whether it's still active
              emergency_list.append(emergency)
        if (emergency_list != []):
          context["emergency_list"] = emergency_list
    else: # Regular user
      emergency_list = []
      doctors_qs = models.Doctor.objects.filter(state="available")
      patients_qs = models.Patient.objects.filter(user=request.user)
      for patient in patients_qs:
        try:
          emergency = models.Emergency_Biometrics.objects.filter(patient=patient).latest("spawn_timestamp")
          if (emergency.active):
            emergency = utils.check_emergency_deactivation(emergency, datetime_obj)
            if (emergency.active): # Check again
              emergency_list.append(emergency)
        except models.Emergency_Biometrics.DoesNotExist:
          pass

      if (doctors_qs.exists()):
        context["doctors_list"] = doctors_qs
      if (patients_qs.exists()):
        context["patients_list"] = patients_qs
        if (emergency_list != []):
          context["emergency_list"] = emergency_list

      form = forms.LinkPatientForm()
      if (request.method == "POST"): # Regular user trying to link its account with some existent patient
        err = 0
        form = forms.LinkPatientForm(request.POST)
        if (form.is_valid()):
          try:
            patient = models.Patient.objects.get(dni=form.cleaned_data["dni"])
            if (patient.user == None):
              patient.user = request.user
              patient.save()
              context["patient_linked"] = 1
            elif (patient.user == request.user):
              err = 1
              output = "You're already following up on that patient."
            else:
              err = 1
              output = "That patient is already linked to another account. Log in with "
              output += "that account to see that patient's information."
          except models.Patient.DoesNotExist:
            err = 1
            output = "No patient has been found with dni '" + form.cleaned_data["dni"] + "'"

        if err:
          context["error_message"] = output
          print(output)

      context["form"] = form

  return render(request, "sigfox_messages/index.html", context=context)

@require_GET
def patient_lookup(request):

  context = {}
  if (request.user.is_authenticated and
      request.user.is_staff):
    patient_list = models.Patient.objects.all()
    if (patient_list.exists()):
      context["patient_list"] = patient_list

  return render(request, "sigfox_messages/patient_lookup.html", context=context)


def add_patient(request):

  context = {}
  if (request.user.is_authenticated and
      request.user.is_staff):
    form = forms.PatientForm()
    if (request.method == "POST"):
      form = forms.PatientForm(request.POST)
      if (form.is_valid()):
        patient = form.save() # Add a new patient to Database
        from sigfox_messages.bot import wait_emergency, manager
        wait_emergency[patient.dni] = manager.Event()
        return HttpResponseRedirect("/sigfox_messages/")

    context["form"] = form

  return render(request, "sigfox_messages/add_patient.html", context=context)


def modify_patient(request, patient_id):

  context = {}
  if (request.user.is_authenticated and
      request.user.is_staff):
    try:
      patient = models.Patient.objects.get(dni=patient_id)
      context["patient"] = patient
    except models.Patient.DoesNotExist:
      print("Patient does not exist", flush=True)
      context["id_not_found"] = patient_id
      return render(request, "sigfox_messages/modify_patient.html", context=context)

    form = forms.ModifyPatientForm()
    if (request.method == "POST"): # Modify Patient fields
      form = forms.ModifyPatientForm(request.POST)
      if (form.is_valid()):
        if ((form.cleaned_data["follow_up"] == "critical") or
            (form.cleaned_data["follow_up"] == "normal")):
          # All checkings passed, update patient fields
          patient.follow_up = form.cleaned_data["follow_up"]
          patient.dev_conf = form.cleaned_data["dev_conf"]
          patient.doctor = form.cleaned_data["doctor"]
          patient.save()
          return HttpResponseRedirect("/sigfox_messages/")
        else:
          output = "Supported values for follow-up are 'normal' or 'critical'"
          print(output)
          context["error_message"] = output

    context["form"] = form

  return render(request, "sigfox_messages/modify_patient.html", context=context)


@require_GET
def patient_detail(request, patient_id):

  datetime_obj = timezone.now()
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
      emergency = models.Emergency_Biometrics.objects.filter(patient=patient).latest("spawn_timestamp")
      if (emergency.active):
        emergency = utils.check_emergency_deactivation(emergency, datetime_obj)
      att_req = models.Attention_request.objects.get(emergency=emergency)

      if (emergency.active):
        context["ongoing_emergency"] = emergency

      if ((att_req.status != "Attended") and
          (request.method == "GET") and
          ("emergency_attended" in request.GET) and
          (request.GET["emergency_attended"] == "true")):
        att_req.status = "Attended"
        att_req.save()
        if (not emergency.active):
          context["attended_set"] = 1

      if (att_req.status == "Attended"):
        context["attended"] = 1
      else:
        context["not_attended"] = 1
    except models.Emergency_Biometrics.DoesNotExist:
      print("Emergency_Biometrics does not exist")
    except models.Attention_request.DoesNotExist:
      print("Attention Request does not exist")

    emerg_qs = models.Emergency_Biometrics.objects.filter(patient=patient)
    bio_qs = models.Biometrics.objects.filter(patient=patient)
    if (emerg_qs.exists()):
      context["emergency_list"] = emerg_qs
    if (bio_qs.exists()):
      context["bio_list"] = bio_qs

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

    if ((patient.user != None) and
        (request.method == "GET") and
        ("unlink_acc" in request.GET) and
        (request.GET["unlink_acc"] == "true")):
      patient.user = None
      patient.save()
      # context["unlink"] = 1
      return HttpResponseRedirect("/sigfox_messages/")

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


def add_doctor(request):

  context = {}
  if (request.user.is_authenticated and
      request.user.is_staff):
    form = forms.DoctorForm()
    if (request.method == "POST"):
      form = forms.DoctorForm(request.POST)
      if (form.is_valid()):
        form.save() # Add a new doctor to Database
        return HttpResponseRedirect("/sigfox_messages/")

    context["form"] = form

  return render(request, "sigfox_messages/add_doctor.html", context=context)


def doctor_detail(request, doctor_id):

  datetime_obj = timezone.now()
  context = {}
  if (request.user.is_authenticated):
    try:
      doctor = models.Doctor.objects.get(id=doctor_id)
      context["doctor"] = doctor
    except models.Doctor.DoesNotExist:
      return render(request, "sigfox_messages/doctor_detail.html", context=context)

    if (request.user.is_staff):
      att_req_qs = models.Attention_request.objects.filter(doctor=doctor,
                                                           status="Unattended")
      if (att_req_qs.exists()):
        context["att_req_qs"] = att_req_qs

      form = forms.DoctorStateForm()
      if (request.method == "POST"):
        form = forms.DoctorStateForm(request.POST)
        if (form.is_valid()):
          if (form.cleaned_data["state"] == "busy" or
              form.cleaned_data["state"] == "available"):
            doctor.state = form.cleaned_data["state"]
            doctor.save()
            return HttpResponseRedirect("/sigfox_messages/")
          else:
            context["wrong_state"] = form.cleaned_data["state"]
      context["form"] = form
    elif (doctor.state == "available"):
      context["available"] = 1
      form = forms.Attention_requestForm()
      if (request.method == "POST"):
        form = forms.Attention_requestForm(request.POST)
        if (form.is_valid()):
          if (form.cleaned_data["request_priority"] == "Normal" or
              form.cleaned_data["request_priority"] == "Urgent"):
            try:
              invalid_patient = 0
              patient = models.Patient.objects.get(dni=form.cleaned_data["dni"])
              patient_qs = models.Patient.objects.filter(user=request.user)
              if (patient_qs.exists() and
                  patient in patient_qs):
                att_req_qs = models.Attention_request.objects.filter(emergency=None,
                                                                     patient=patient,
                                                                     status="Unattended")
                if (not att_req_qs.exists()):
                  models.Attention_request.objects.create(emergency=None,
                                                          patient=patient,
                                                          doctor=doctor,
                                                          request_timestamp=datetime_obj,
                                                          request_priority=form.cleaned_data["request_priority"],
                                                          status="Unattended")
                  return HttpResponseRedirect("/sigfox_messages/")
                else:
                  context["already_assigned"] = 1
              else:
                invalid_patient = 1
            except models.Patient.DoesNotExist:
              invalid_patient = 1

            if invalid_patient:
              context["invalid_patient"] = 1
          else:
            context["invalid_priority"] = 1
      context["form"] = form

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


def add_device(request):

  context = {}
  if (request.user.is_authenticated and
      request.user.is_staff):
    form = forms.Device_ConfigForm()
    if (request.method == "POST"):
      form = forms.Device_ConfigForm(request.POST)
      if (form.is_valid()):
        form.save() # Add a new device to Database
        return HttpResponseRedirect("/sigfox_messages/")

    context["form"] = form

  return render(request, "sigfox_messages/add_device.html", context=context)


def modify_device_config(request, device_id):

  context = {}
  if (request.user.is_authenticated and
      request.user.is_staff):
    try:
      dev_conf = models.Device_Config.objects.get(dev_id=device_id)
      context["dev_conf"] = dev_conf
    except models.Device_Config.DoesNotExist:
      print("Device_Config does not exist", flush=True)
      context["id_not_found"] = device_id
      return render(request, "sigfox_messages/modify_device_config.html", context=context)

    form = forms.ModifyDevice_ConfigForm()
    if (request.method == "POST"):
      form = forms.ModifyDevice_ConfigForm(request.POST)
      if (form.is_valid()):
        dev_conf.higher_bpm_limit = form.cleaned_data["higher_bpm_limit"]
        dev_conf.lower_bpm_limit = form.cleaned_data["lower_bpm_limit"]
        dev_conf.higher_ebpm_limit = form.cleaned_data["higher_ebpm_limit"]
        dev_conf.lower_ebpm_limit = form.cleaned_data["lower_ebpm_limit"]
        dev_conf.bpm_limit_window = form.cleaned_data["bpm_limit_window"]
        dev_conf.min_delay = form.cleaned_data["min_delay"]
        dev_conf.save()
        return HttpResponseRedirect("/sigfox_messages/")

    context["form"] = form

  return render(request, "sigfox_messages/modify_device_config.html", context=context)


@require_GET
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

  return render(request, "sigfox_messages/device_config_detail.html", context=context)


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


@require_GET
def biometrics_detail(request, biometrics_id):

  context = {}
  try:
    bio = models.Biometrics.objects.get(id=biometrics_id)
    if ((not request.user.is_staff) and (request.user != bio.patient.user)):
      context["not_allowed"] = 1
    else:
      dev_hist = models.Device_History.objects.get(dev_conf=bio.patient.dev_conf,
                                                   date=bio.date)
      context["bio"] = bio
      context["dev_hist"] = dev_hist
      context["ranges"] = utils.get_ranges(dev_hist.lower_bpm_limit,
                                           dev_hist.higher_bpm_limit,
                                           bio=bio)
      if ((dev_hist.continuous_delivery) and
          (dev_hist.uplink_count > 1)):
        delta = dev_hist.last_msg_time - dev_hist.running_since
        context["time_diff"] = utils.get_interval(delta)

  except models.Biometrics.DoesNotExist:
    print("Biometrics does not exist")
  except models.Device_History.DoesNotExist:
    print("Device_History does not exist")

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
      dev_hist = models.Device_History.objects.filter(dev_conf=patient.dev_conf).latest("date")
      context["last_day"] = 1
      context["bio"] = bio_24
      context["dev_hist"] = dev_hist
      context["ranges"] = utils.get_ranges(dev_hist.lower_bpm_limit,
                                           dev_hist.higher_bpm_limit,
                                           bio_24=bio_24)
      if ((dev_hist.continuous_delivery) and
          (dev_hist.uplink_count > 1)):
        delta = dev_hist.last_msg_time - dev_hist.running_since
        context["time_diff"] = utils.get_interval(delta)

  except models.Patient.DoesNotExist:
    print("Patient does not exist")
  except models.Biometrics_24.DoesNotExist:
    print("Biometrics_24 does not exist")
  except models.Device_History.DoesNotExist:
    print("Device_History does not exist")

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
      dev_hist = models.Device_History.objects.get(dev_conf=emergency.patient.dev_conf,
                                                   date=emergency.spawn_timestamp.date())
      if (emergency.active):
        datetime_obj = timezone.now()
        emergency = utils.check_emergency_deactivation(emergency, datetime_obj)

      if ((not emergency.active) and
          (emergency.termination_timestamp != None) and
          (emergency.emsg_count > 1)):
        delta = emergency.termination_timestamp - emergency.spawn_timestamp
        context["time_diff"] = utils.get_interval(delta)

      context["ebio"] = emergency
      epayload_qs = models.Emergency_Payload.objects.filter(emergency=emergency)
      if (epayload_qs.exists()):
        context["epayload_qs"] = epayload_qs
      context["ranges"] = utils.get_ranges(dev_hist.lower_bpm_limit,
                                           dev_hist.higher_bpm_limit,
                                           emergency=emergency)
  except models.Emergency_Biometrics.DoesNotExist:
    print("Emergency not found")
  except models.Device_History.DoesNotExist:
    print("Device_History not found")

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
      dev_hist = models.Device_History.objects.get(dev_conf=epayload.emergency.patient.dev_conf,
                                                   date=epayload.emergency.spawn_timestamp.date())
      context["epayload"] = epayload
      context["ranges"] = utils.get_ranges(dev_hist.lower_bpm_limit,
                                           dev_hist.higher_bpm_limit,
                                           epayload=epayload)
  except models.Emergency_Payload.DoesNotExist:
    print("Epayload not found")
  except models.Device_History.DoesNotExist:
    print("Device_History not found")

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
    if ((att_req.status != "Attended") and
        ("emergency_attended" in request.GET) and
        (request.GET["emergency_attended"] == "true")):
      att_req.status = "Attended"
      att_req.save()
    elif (att_req.status == "Unattended"):
      context["not_attended"] = 1

  return render(request, "sigfox_messages/attention_request_detail.html",
                context=context)

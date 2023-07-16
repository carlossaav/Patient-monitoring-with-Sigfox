from django.db import models
#from django.contrib.auth.models import User

class Device_Config(models.Model):

  dev_id = models.CharField(max_length=50, primary_key=True)
  higher_bpm_limit = models.CharField(max_length=3)
  lower_bpm_limit = models.CharField(max_length=3)
  higher_ebpm_limit = models.CharField(max_length=3)
  lower_ebpm_limit = models.CharField(max_length=3)
  bpm_limit_window = models.CharField(max_length=4)
  min_delay = models.CharField(max_length=4)


class Device_History(models.Model):

  dev_conf = models.ForeignKey(Device_Config, on_delete=models.CASCADE)
  date = models.CharField(max_length=10) # dd/mm/yy format
  running_since = models.CharField(max_length=8) # hh:mm:ss format
  last_msg_time = models.CharField(max_length=8) # hh:mm:ss format
  last_dev_state = models.CharField(max_length=25)
  last_known_loc = models.CharField(max_length=50)
  uplink_count = models.CharField(max_length=3)
  downlink_count = models.CharField(max_length=3)


class Doctor(models.Model):

  name = models.CharField(max_length=25)
  surname = models.CharField(max_length=50)
  # dni = models.CharField(max_length=25)
  state = models.CharField(max_length=25)


class Patient(models.Model):

  dni = models.CharField(max_length=25, primary_key=True)
  name = models.CharField(max_length=25)
  surname = models.CharField(max_length=50)
  age = models.CharField(max_length=3)
  dev_conf = models.OneToOneField(Device_Config, on_delete=models.SET_NULL, blank=True, null=True)
  doctor = models.ForeignKey(Doctor, on_delete=models.SET_NULL, blank=True, null=True)
  follow_up = models.CharField(max_length=25)


class Contact(models.Model):

  echat_id = models.CharField(max_length=50, primary_key=True)
  chat_username = models.CharField(max_length=50) # Chat's username
  echat_state = models.CharField(max_length=50) # Chat's state
  etelephone = models.CharField(max_length=50) # For SMS contact
  sms_alerts = models.CharField(max_length=3)  # ("Yes/No")


class Patient_Contact(models.Model):

  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
  contact = models.ForeignKey(Contact, on_delete=models.CASCADE)


class Patient_Device_History(models.Model):

  dev_hist = models.OneToOneField(Device_History, on_delete=models.CASCADE, primary_key=True)
  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)


class Emergency_Biometrics(models.Model):

  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
  emerg_date = models.CharField(max_length=10) # dd/mm/yy format
  emerg_time = models.CharField(max_length=8) # hh:mm:ss format
  emsg_count = models.CharField(max_length=2)
  active = models.CharField(max_length=25)

  bpm_time = models.CharField(max_length=50)
  ibi_time = models.CharField(max_length=50)

  avg_bpm = models.CharField(max_length=3)
  sum_bpm = models.CharField(max_length=25)
  avg_ibi = models.CharField(max_length=5)
  sum_ibi = models.CharField(max_length=25)
  max_bpm = models.CharField(max_length=3)
  max_ibi = models.CharField(max_length=5)
  min_bpm = models.CharField(max_length=3)
  min_ibi = models.CharField(max_length=5)

  lower_range = models.CharField(max_length=3) # 0.yz format (percentage)
  lower_range_sum = models.CharField(max_length=25)
  second_range = models.CharField(max_length=3)
  second_range_sum = models.CharField(max_length=25)
  third_range = models.CharField(max_length=3)
  third_range_sum = models.CharField(max_length=25)
  higher_range = models.CharField(max_length=3)
  higher_range_sum = models.CharField(max_length=25)

  last_temp = models.CharField(max_length=4)
  sum_temp = models.CharField(max_length=10)
  avg_temp = models.CharField(max_length=4)
  max_temp = models.CharField(max_length=4)
  min_temp = models.CharField(max_length=4)


class Emergency_Payload(models.Model):

  emergency = models.ForeignKey(Emergency_Biometrics, on_delete=models.CASCADE)
  econd_payload = models.CharField(max_length=3) # payload where an emergency condition was detected ("Yes/No")
  msg_type = models.CharField(max_length=25)
  payload_format = models.CharField(max_length=1)

  avg_bpm = models.CharField(max_length=3)
  avg_ibi = models.CharField(max_length=5)
  max_bpm = models.CharField(max_length=3)
  max_ibi = models.CharField(max_length=5)
  min_bpm = models.CharField(max_length=3)
  min_ibi = models.CharField(max_length=5)

  lower_range = models.CharField(max_length=3)
  second_range = models.CharField(max_length=3)
  third_range = models.CharField(max_length=3)
  higher_range = models.CharField(max_length=3)

  temp = models.CharField(max_length=5)
  elapsed_ms = models.CharField(max_length=50)


class Attention_request(models.Model):

  emergency = models.OneToOneField(Emergency_Biometrics, on_delete=models.SET_NULL, blank=True, null=True)
  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)

  request_date = models.CharField(max_length=10) # dd/mm/yy format
  request_time = models.CharField(max_length=8) # hh:mm:ss format
  request_type = models.CharField(max_length=25)
  communication_status = models.CharField(max_length=25) # ("Processing/Notified(SMS/Whatsssap)/Received(SMS/Whatsssap; i.e. one or more users have
  # accesed provided URL(s) from their telephones/Communication Finished")
#  emerg_state = models.CharField(max_length=25)


class Doctor_Request(models.Model):

  attention_request = models.OneToOneField(Attention_request, on_delete=models.CASCADE, primary_key=True)
  doctor = models.ForeignKey(Doctor, on_delete=models.SET_NULL, blank=True, null=True)
  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
  request_state = models.CharField(max_length=25) # ("Pending/Accepted/Attended")


class Biometrics(models.Model):

  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
  date = models.CharField(max_length=10) # dd/mm/yy format

  avg_bpm = models.CharField(max_length=3)
  avg_ibi = models.CharField(max_length=5)
  max_bpm = models.CharField(max_length=3)
  max_ibi = models.CharField(max_length=5)
  min_bpm = models.CharField(max_length=3)
  min_ibi = models.CharField(max_length=5)

  lower_range = models.CharField(max_length=3)
  second_range = models.CharField(max_length=3)
  third_range = models.CharField(max_length=3)
  higher_range = models.CharField(max_length=3)

  last_temp = models.CharField(max_length=4)
  avg_temp = models.CharField(max_length=4)
  max_temp = models.CharField(max_length=4)
  min_temp = models.CharField(max_length=4)

  last_alarm_time = models.CharField(max_length=8) # hh:mm:ss format
  last_limit_time = models.CharField(max_length=8)

  # Look at max_bpm/min_bpm fields on LIMITS_MSG message, then update this field on database if proceeds. Important timestamp for the medical team.
  last_elimit_time = models.CharField(max_length=8)


class Biometrics_24(models.Model):

  patient = models.OneToOneField(Patient, on_delete=models.CASCADE, primary_key=True)
  bpm_time = models.CharField(max_length=50)
  ibi_time = models.CharField(max_length=50)

  avg_bpm = models.CharField(max_length=3)
  sum_bpm = models.CharField(max_length=25)
  avg_ibi = models.CharField(max_length=5)
  sum_ibi = models.CharField(max_length=25)
  max_bpm = models.CharField(max_length=3)
  max_ibi = models.CharField(max_length=5)
  min_bpm = models.CharField(max_length=3)
  min_ibi = models.CharField(max_length=5)

  lower_range = models.CharField(max_length=3) # 0.yz format (percentage)
  lower_range_sum = models.CharField(max_length=25)
  second_range = models.CharField(max_length=3)
  second_range_sum = models.CharField(max_length=25)
  third_range = models.CharField(max_length=3)
  third_range_sum = models.CharField(max_length=25)
  higher_range = models.CharField(max_length=3)
  higher_range_sum = models.CharField(max_length=25)

  last_temp = models.CharField(max_length=5)
  sum_temp = models.CharField(max_length=10)
  avg_temp = models.CharField(max_length=5)
  max_temp = models.CharField(max_length=5)
  min_temp = models.CharField(max_length=5)

  last_alarm_time = models.CharField(max_length=8) # hh:mm:ss format
  last_limit_time = models.CharField(max_length=8)

  # Look at max_bpm/min_bpm fields on LIMITS_MSG message, then update this field on database if proceeds. Important timestamp for the medical team.
  last_elimit_time = models.CharField(max_length=8)

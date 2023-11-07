from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator

class Device_Config(models.Model):

  dev_id = models.CharField(max_length=15, primary_key=True)
  higher_bpm_limit = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)])
  lower_bpm_limit = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)])
  higher_ebpm_limit = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)])
  lower_ebpm_limit = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)])
  bpm_limit_window = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(127)])
  min_delay = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(65535)])

  def __str__(self):
    return self.dev_id


class Device_History(models.Model):

  dev_conf = models.ForeignKey(Device_Config, on_delete=models.CASCADE)
  date = models.DateField()
  running_since = models.DateTimeField()
  last_msg_time = models.DateTimeField()
  last_dev_state = models.CharField(max_length=25)
  last_known_latitude = models.CharField(max_length=25)
  last_known_longitude = models.CharField(max_length=25)
  uplink_count = models.IntegerField()
  downlink_count = models.IntegerField()
  higher_bpm_limit = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)])
  lower_bpm_limit = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)])
  continuous_delivery = models.BooleanField(default=True)

  def __str__(self):
    return str(self.dev_conf) + str(self.date)


class Doctor(models.Model):

  name = models.CharField(max_length=25)
  surname = models.CharField(max_length=50)
  state = models.CharField(max_length=25)

  def __str__(self):
    return self.name + " " + self.surname


class Patient(models.Model):

  dni = models.CharField(max_length=10, primary_key=True)
  name = models.CharField(max_length=25)
  surname = models.CharField(max_length=50)
  user = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True)
  age = models.CharField(max_length=3)
  dev_conf = models.OneToOneField(Device_Config, on_delete=models.SET_NULL, null=True)
  doctor = models.ForeignKey(Doctor, on_delete=models.SET_NULL, null=True)
  follow_up = models.CharField(max_length=25)

  def __str__(self):
    return self.dni


class Contact(models.Model):

  echat_id = models.CharField(max_length=50, primary_key=True)
  chat_username = models.CharField(max_length=50) # Chat's username
  echat_state = models.CharField(max_length=50) # Chat's state
  phone_number = models.CharField(max_length=50) # For SMS contact
  sms_alerts = models.CharField(max_length=3)  # ("Yes/No")

  def __str__(self):
    return self.echat_id


class Patient_Contact(models.Model):

  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
  contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
  comm_status = models.CharField(max_length=25) # Emergency notification 'state' ("Pending"/"Done")

  def __str__(self):
    return str(self.patient) + ", " + str(self.contact)


class Emergency_Biometrics(models.Model):

  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
  spawn_timestamp = models.DateTimeField()
  termination_timestamp = models.DateTimeField(null=True)
  emsg_count = models.IntegerField()
  active = models.BooleanField()

  bpm_time = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  ibi_time = models.IntegerField(validators=[MinValueValidator(0)], null=True)

  avg_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  sum_bpm = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  avg_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  sum_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  max_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  max_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  min_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  min_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)

  lower_range = models.CharField(max_length=5)
  lower_range_sum = models.CharField(max_length=25)
  second_range = models.CharField(max_length=5)
  second_range_sum = models.CharField(max_length=25)
  third_range = models.CharField(max_length=5)
  third_range_sum = models.CharField(max_length=25)
  higher_range = models.CharField(max_length=5)
  higher_range_sum = models.CharField(max_length=25)

  last_temp = models.CharField(max_length=6)
  sum_temp = models.CharField(max_length=15)
  avg_temp = models.CharField(max_length=6)
  max_temp = models.CharField(max_length=6)
  min_temp = models.CharField(max_length=6)
  
  def __str__(self):
    return str(self.spawn_timestamp)


class Emergency_Payload(models.Model):

  emergency = models.ForeignKey(Emergency_Biometrics, on_delete=models.CASCADE)
  ereason_payload = models.CharField(max_length=3) # payload where an emergency condition was detected ("Yes/No")
  msg_type = models.CharField(max_length=25)
  payload_format = models.CharField(max_length=1)

  avg_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  avg_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  max_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  max_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  min_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  min_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)

  lower_range = models.CharField(max_length=5)
  second_range = models.CharField(max_length=5)
  third_range = models.CharField(max_length=5)
  higher_range = models.CharField(max_length=5)

  temp = models.CharField(max_length=15)
  elapsed_ms = models.CharField(max_length=50)

  def __str__(self):
    return str(self.id)


class Attention_request(models.Model):

  emergency = models.OneToOneField(Emergency_Biometrics, on_delete=models.SET_NULL, blank=True, null=True)
  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
  doctor = models.ForeignKey(Doctor, on_delete=models.SET_NULL, null=True)

  request_timestamp = models.DateTimeField()
  request_priority = models.CharField(max_length=25) # ("Normal"/"Urgent")
  status = models.CharField(max_length=25) # ("Attended"/"Unattended")
#  emerg_state = models.CharField(max_length=25)

  def __str__(self):
    return ("(" + str(self.request_priority) + "): " + str(self.request_timestamp))


class Biometrics(models.Model):

  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
  date = models.DateField()

  avg_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  avg_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  max_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  max_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  min_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  min_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)

  lower_range = models.CharField(max_length=5)
  second_range = models.CharField(max_length=5)
  third_range = models.CharField(max_length=5)
  higher_range = models.CharField(max_length=5)

  last_temp = models.CharField(max_length=6)
  avg_temp = models.CharField(max_length=6)
  max_temp = models.CharField(max_length=6)
  min_temp = models.CharField(max_length=6)

  last_alarm_time = models.DateTimeField(blank=True, null=True)
  last_limit_time = models.DateTimeField(blank=True, null=True)

  # Look at max_bpm/min_bpm fields on LIMITS_MSG message, then update this field on database if proceeds.
  # Important timestamp for the medical team.
  last_elimit_time = models.DateTimeField(blank=True, null=True)

  def __str__(self):
    return str(self.patient) + ", " + str(self.date)


class Biometrics_24(models.Model):

  patient = models.OneToOneField(Patient, on_delete=models.CASCADE, primary_key=True)
  bpm_time = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  ibi_time = models.IntegerField(validators=[MinValueValidator(0)], null=True)

  avg_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  sum_bpm = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  avg_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  sum_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  max_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  max_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  min_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  min_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)

  lower_range = models.CharField(max_length=5)
  lower_range_sum = models.CharField(max_length=25)
  second_range = models.CharField(max_length=5)
  second_range_sum = models.CharField(max_length=25)
  third_range = models.CharField(max_length=5)
  third_range_sum = models.CharField(max_length=25)
  higher_range = models.CharField(max_length=5)
  higher_range_sum = models.CharField(max_length=25)

  last_temp = models.CharField(max_length=6)
  sum_temp = models.CharField(max_length=15)
  avg_temp = models.CharField(max_length=6)
  max_temp = models.CharField(max_length=6)
  min_temp = models.CharField(max_length=6)

  last_alarm_time = models.DateTimeField(blank=True, null=True)
  last_limit_time = models.DateTimeField(blank=True, null=True)

  # Look at max_bpm/min_bpm fields on LIMITS_MSG message, then update this field on database if proceeds.
  # Important timestamp for the medical team.
  last_elimit_time = models.DateTimeField(blank=True, null=True)

  def __str__(self):
    return str(self.patient)

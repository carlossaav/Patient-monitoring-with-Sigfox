from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator

class Device_Config(models.Model):

  dev_id = models.CharField(max_length=15, primary_key=True)
  lower_bpm_limit = models.IntegerField(validators=[MinValueValidator(31), MaxValueValidator(220)], blank=False, null=False)
  lower_ebpm_limit = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(220)], blank=True, null=False)
  higher_bpm_limit = models.IntegerField(validators=[MinValueValidator(40), MaxValueValidator(224)], blank=False, null=False)
  higher_ebpm_limit = models.IntegerField(validators=[MinValueValidator(40), MaxValueValidator(255)], blank=True, null=False)
  min_temp = models.FloatField(validators=[MinValueValidator(35.0), MaxValueValidator(38.8)], blank=False, null=False)
  max_temp = models.FloatField(validators=[MinValueValidator(35.1), MaxValueValidator(38.9)], blank=False, null=False)
  bpm_limit_window = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(127)], blank=False, null=False)
  min_delay = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(15)], blank=False, null=False)

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
  sms_alerts = models.BooleanField(default=True)

  def __str__(self):
    return self.echat_id


class Patient_Contact(models.Model):

  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
  contact = models.ForeignKey(Contact, on_delete=models.CASCADE)
  comm_status = models.CharField(max_length=25) # Emergency notification 'state' ("Pending"/"Done")
  stop_set = models.BooleanField(default=False)

  def __str__(self):
    return str(self.patient) + ", " + str(self.contact)


class Message_Timestamp(models.Model):

  last_alarm_time = models.DateTimeField(blank=True, null=True)
  last_limit_time = models.DateTimeField(blank=True, null=True)
  last_elimit_time = models.DateTimeField(blank=True, null=True)

  class Meta:
    abstract = True # Abstract class, don't create a table for it on database


class Uplink_Statistics(models.Model):

  avg_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  avg_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  max_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  max_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  min_bpm = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(255)], null=True)
  min_ibi = models.IntegerField(validators=[MinValueValidator(0)], null=True)

  lower_range = models.FloatField(null=True)
  second_range = models.FloatField(null=True)
  third_range = models.FloatField(null=True)
  higher_range = models.FloatField(null=True)

  last_temp = models.FloatField(null=True)

  class Meta:
    abstract = True # Abstract class, don't create a table for it on database


class Interval_Temperature_Statistics(models.Model):

  avg_temp = models.FloatField(null=True)
  max_temp = models.FloatField(null=True)
  min_temp = models.FloatField(null=True)

  class Meta:
    abstract = True # Abstract class, don't create a table for it on database


class Interval_Statistics(models.Model):

  bpm_time = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  ibi_time = models.IntegerField(validators=[MinValueValidator(0)], null=True)

  sum_bpm = models.PositiveIntegerField(validators=[MinValueValidator(0)], null=True)
  sum_ibi = models.PositiveIntegerField(validators=[MinValueValidator(0)], null=True)

  lower_range_samples = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  second_range_samples = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  third_range_samples = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  higher_range_samples = models.IntegerField(validators=[MinValueValidator(0)], null=True)

  temp_samples = models.IntegerField(validators=[MinValueValidator(0)], null=True)
  sum_temp = models.FloatField(null=True)

  class Meta:
    abstract = True # Abstract class, don't create a table for it on database


class Biometrics(Message_Timestamp, 
                 Uplink_Statistics,
                 Interval_Temperature_Statistics):

  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
  date = models.DateField()

  def __str__(self):
    return str(self.patient) + ", " + str(self.date)


class Biometrics_24(Message_Timestamp,
                    Uplink_Statistics,
                    Interval_Temperature_Statistics,
                    Interval_Statistics):

  patient = models.OneToOneField(Patient, on_delete=models.CASCADE, primary_key=True)

  def __str__(self):
    return str(self.patient)


class Emergency_Biometrics(Message_Timestamp,
                           Uplink_Statistics,
                           Interval_Temperature_Statistics,
                           Interval_Statistics):

  patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
  spawn_timestamp = models.DateTimeField()
  termination_timestamp = models.DateTimeField(null=True)
  emsg_count = models.IntegerField()
  active = models.BooleanField()

  def __str__(self):
    return str(self.spawn_timestamp)


class Emergency_Payload(Uplink_Statistics):

  emergency = models.ForeignKey(Emergency_Biometrics, on_delete=models.CASCADE)
  ereason_payload = models.BooleanField(default=True) # payload where an emergency condition was detected (True/False)
  msg_type = models.CharField(max_length=25)
  payload_format = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(7)])

  elapsed_ms = models.PositiveIntegerField()

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

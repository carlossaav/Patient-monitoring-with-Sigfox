from django import forms
from .models import Attention_request, Device_Config, Doctor, Patient

class DoctorStateForm(forms.Form):
  state = forms.CharField(max_length=25)


class DoctorForm(forms.ModelForm):
  class Meta:
    model = Doctor
    fields = '__all__'


class Attention_requestForm(forms.Form):
  dni = forms.CharField(max_length=10)
  request_priority = forms.CharField(max_length=25)


class Device_ConfigForm(forms.ModelForm):
  class Meta:
    model = Device_Config
    fields = '__all__'


class ModifyDevice_ConfigForm(forms.ModelForm):
  class Meta:
    model = Device_Config
    exclude = ["dev_id"]


class PatientForm(forms.ModelForm):
  class Meta:
    model = Patient
    fields = '__all__'


class ModifyPatientForm(forms.ModelForm):
  class Meta:
    model = Patient
    fields = ["dev_conf", "doctor", "follow_up"]


class LinkPatientForm(forms.Form):
  dni = forms.CharField(max_length=10)

from django.urls import include, path
from sigfox_messages import bot, views

urlpatterns= [
  path('register/', views.register, name="register"),
  path('accounts/', include("django.contrib.auth.urls")),
  path('', views.index, name="index"),
  path('downlink/<dev_id>', views.downlink, name="downlink_req"),
  path('uplink/', views.uplink, name="uplink_req"),
  path('add_doctor/', views.add_doctor, name="add_doctor"),
  path('modify_patient/<patient_id>', views.modify_patient, name="modify_patient"),
  path('add_patient/', views.add_patient, name="add_patient"),
  path('add_device/', views.add_device, name="add_device"),
  path('doctor_lookup/', views.doctor_lookup, name="doctor_lookup"),
  path('pdoctor_lookup/<int:doctor_id>', views.pdoctor_lookup, name="pdoctor_lookup"),
  path('patient_lookup/', views.patient_lookup, name="patient_lookup"),
  path('device_lookup/', views.device_lookup, name="device_lookup"),
  path('patient/<patient_id>', views.patient_detail, name="patient_detail"),
  path('modify_device_config/<device_id>', views.modify_device_config, name="modify_device_config"),
  path('device_config/<device_id>', views.device_config_detail, name="device_config_detail"),
  path('device_hist/<int:device_hist_id>', views.device_hist_detail, name="device_hist_detail"),
  path('doctor/<int:doctor_id>', views.doctor_detail, name="doctor_detail"),
  path('biometrics/<int:biometrics_id>', views.biometrics_detail, name="biometrics_detail"),
  path('biometrics_24/<patient_id>', views.biometrics24_detail, name="biometrics24_detail"),
  path('emergency/<int:emergency_id>', views.emergency_detail, name="emergency_detail"),
  path('epayload/<int:epayload_id>', views.epayload_detail, name="epayload_detail"),
  path('att_req/<int:att_req_id>', views.att_req_detail, name="att_req_detail"),
]

bot.main()

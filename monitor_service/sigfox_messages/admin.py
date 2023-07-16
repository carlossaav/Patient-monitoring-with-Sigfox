from django.contrib import admin
from sigfox_messages import models

# Register your models here.

admin.site.register(models.Doctor)
admin.site.register(models.Doctor_Request)
admin.site.register(models.Device_Config)
admin.site.register(models.Device_History)
admin.site.register(models.Patient)
admin.site.register(models.Patient_Device_History)
admin.site.register(models.Biometrics)
admin.site.register(models.Biometrics_24)
admin.site.register(models.Emergency_Biometrics)
admin.site.register(models.Emergency_Payload)
admin.site.register(models.Attention_request)
admin.site.register(models.Contact)
admin.site.register(models.Patient_Contact)

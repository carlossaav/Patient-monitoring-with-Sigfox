from django.urls import path
from sigfox_messages import views

urlpatterns= [
  path('downlink/<dev_id>', views.downlink, name="downlink_req"),
  path('uplink/', views.uplink, name="uplink_req"),
]

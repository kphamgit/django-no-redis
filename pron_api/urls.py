from django.urls import path
from . import views

urlpatterns = [
    # Placeholder; add real pronunciation endpoints here.
    path("ping/", views.ping, name="pron-ping"),
    path("uberduck_arpabet/", views.uberduck_arpabet, name="uberduck_arpabet"),
]

from django.urls import path

from . import views

BASE_URLS = "plugins"

urlpatterns = [
    path("", views.index, name="g3w-plugins"),
    path("status/", views.job_status, name="g3w-plugins-status"),
    path("version/", views.latest_version, name="g3w-plugins-version"),
]

#
#    Copyright 2019 Red Hat, Inc.
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
"""rbac URL Configuration.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.0/topics/http/urls/
"""
import os
import re

from django.conf.urls import include, url
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path
from management import consumers

API_PATH_PREFIX = os.getenv("API_PATH_PREFIX", "api/")
if API_PATH_PREFIX != "":
    if API_PATH_PREFIX.startswith("/"):
        API_PATH_PREFIX = API_PATH_PREFIX[1:]
    if not API_PATH_PREFIX.endswith("/"):
        API_PATH_PREFIX = API_PATH_PREFIX + "/"

WSS_PATH_PREFIX = re.sub("api", "wss", API_PATH_PREFIX)

# pylint: disable=invalid-name
urlpatterns = [
    url(r"^{}v1/".format(API_PATH_PREFIX), include("api.urls")),
    url(r"^{}v1/".format(API_PATH_PREFIX), include("management.urls")),
    url(r"^_private/", include("internal.urls")),
    path("", include("django_prometheus.urls")),
]

urlpatterns += staticfiles_urlpatterns()
websocket_urlpatterns = [
    url(r"^{}v1/cross-account-requests/$".format(WSS_PATH_PREFIX), consumers.RbacConsumer.as_asgi())
]

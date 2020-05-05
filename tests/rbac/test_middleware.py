#
# Copyright 2019 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
"""Test the project middleware."""
import collections
import os
from unittest.mock import Mock

from django.db import connection
from django.test import TestCase
from django.urls import reverse
from api.common import RH_IDENTITY_HEADER

from rest_framework import status
from rest_framework.test import APIClient

from api.models import Tenant, User
from api.serializers import create_schema_name
from tests.identity_request import IdentityRequest
from rbac.middleware import HttpResponseUnauthorizedRequest, IdentityHeaderMiddleware, TENANTS
from management.models import Access, Group, Principal, Policy, ResourceDefinition, Role


class EnvironmentVarGuard(collections.abc.MutableMapping):

    """Class to help protect the environment variable properly.  Can be used as
    a context manager."""

    def __init__(self):
        self._environ = os.environ
        self._changed = {}

    def __getitem__(self, envvar):
        return self._environ[envvar]

    def __setitem__(self, envvar, value):
        # Remember the initial value on the first access
        if envvar not in self._changed:
            self._changed[envvar] = self._environ.get(envvar)
        self._environ[envvar] = value

    def __delitem__(self, envvar):
        # Remember the initial value on the first access
        if envvar not in self._changed:
            self._changed[envvar] = self._environ.get(envvar)
        if envvar in self._environ:
            del self._environ[envvar]

    def keys(self):
        return self._environ.keys()

    def __iter__(self):
        return iter(self._environ)

    def __len__(self):
        return len(self._environ)

    def set(self, envvar, value):
        self[envvar] = value

    def unset(self, envvar):
        del self[envvar]

    def __enter__(self):
        return self

    def __exit__(self, *ignore_exc):
        for (k, v) in self._changed.items():
            if v is None:
                if k in self._environ:
                    del self._environ[k]
            else:
                self._environ[k] = v
        os.environ = self._environ


class RbacTenantMiddlewareTest(IdentityRequest):
    """Tests against the rbac tenant middleware."""

    def setUp(self):
        """Set up middleware tests."""
        super().setUp()
        self.user_data = self._create_user_data()
        self.customer = self._create_customer_data()
        self.schema_name = create_schema_name(self.customer["account_id"])
        self.request_context = self._create_request_context(self.customer, self.user_data, create_customer=False)
        self.request = self.request_context["request"]
        self.request.path = "/api/v1/providers/"
        user = User()
        user.username = self.user_data["username"]
        user.account = self.customer_data["account_id"]
        self.request.user = user

    def test_get_tenant_with_user(self):
        """Test that the customer tenant is returned."""
        mock_request = self.request
        middleware = IdentityHeaderMiddleware()
        result = middleware.get_tenant(Tenant, "localhost", mock_request)
        self.assertEqual(result.schema_name, create_schema_name(mock_request.user.account))

    def test_get_tenant_with_no_user(self):
        """Test that a 401 is returned."""
        mock_request = Mock(path="/api/v1/providers/", user=None)
        middleware = IdentityHeaderMiddleware()
        result = middleware.process_request(mock_request)
        self.assertIsInstance(result, HttpResponseUnauthorizedRequest)

    def test_get_tenant_user_not_found(self):
        """Test that a 401 is returned."""
        mock_user = Mock(username="mockuser", system=False)
        mock_request = Mock(path="/api/v1/providers/", user=mock_user)
        middleware = IdentityHeaderMiddleware()
        result = middleware.process_request(mock_request)
        self.assertIsInstance(result, HttpResponseUnauthorizedRequest)


class IdentityHeaderMiddlewareTest(IdentityRequest):
    """Tests against the rbac tenant middleware."""

    def setUp(self):
        """Set up middleware tests."""
        super().setUp()
        self.user_data = self._create_user_data()
        self.customer = self._create_customer_data()
        self.schema_name = create_schema_name(self.customer["account_id"])
        self.request_context = self._create_request_context(self.customer, self.user_data, create_customer=False)
        self.request = self.request_context["request"]
        self.request.path = "/api/v1/providers/"
        self.request.META["QUERY_STRING"] = ""

    def test_process_status(self):
        """Test that the request gets a user."""
        mock_request = Mock(path="/api/v1/status/")
        middleware = IdentityHeaderMiddleware()
        middleware.process_request(mock_request)
        self.assertTrue(hasattr(mock_request, "user"))

    def test_process_response(self):
        """Test that the process response functions correctly."""
        mock_request = Mock(path="/api/v1/status/")
        mock_response = Mock(status_code=200)
        middleware = IdentityHeaderMiddleware()
        response = middleware.process_response(mock_request, mock_response)
        self.assertEqual(response, mock_response)

    def test_process_not_status(self):
        """Test that the customer, tenant and user are created."""
        mock_request = self.request
        middleware = IdentityHeaderMiddleware()
        middleware.process_request(mock_request)
        self.assertTrue(hasattr(mock_request, "user"))
        self.assertEqual(mock_request.user.username, self.user_data["username"])
        tenant = Tenant.objects.get(schema_name=self.schema_name)
        self.assertIsNotNone(tenant)

    def test_process_no_customer(self):
        """Test that the customer, tenant and user are not created."""
        customer = self._create_customer_data()
        account_id = customer["account_id"]
        del customer["account_id"]
        request_context = self._create_request_context(customer, self.user_data, create_customer=False)
        mock_request = request_context["request"]
        mock_request.path = "/api/v1/providers/"
        middleware = IdentityHeaderMiddleware()
        middleware.process_request(mock_request)
        self.assertTrue(hasattr(mock_request, "user"))
        with self.assertRaises(Tenant.DoesNotExist):
            Tenant.objects.get(schema_name=self.schema_name)

    def test_race_condition_customer(self):
        """Test case where another request may create the tenant in a race condition."""
        mock_request = self.request
        mock_request.user = User()
        mock_request.user.username = self.user_data["username"]
        mock_request.user.account = self.customer_data["account_id"]
        orig_cust = IdentityHeaderMiddleware().get_tenant(None, None, mock_request)
        dup_cust = IdentityHeaderMiddleware().get_tenant(None, None, mock_request)
        self.assertEqual(orig_cust, dup_cust)


class ServiceToService(IdentityRequest):
    """Tests requests without an identity header."""

    def setUp(self):
        """Setup tests."""
        self.env = EnvironmentVarGuard()
        self.env.set("SERVICE_PSKS", '{"catalog": {"secret": "abc123"}}')
        self.account_id = "1234"
        self.service_headers = {
            "HTTP_X_RH_RBAC_PSK": "abc123",
            "HTTP_X_RH_RBAC_ACCOUNT": self.account_id,
            "HTTP_X_RH_RBAC_CLIENT_ID": "catalog",
        }

    def test_no_identity_or_service_headers_returns_401(self):
        url = reverse("group-list")
        client = APIClient()
        self.service_headers = {}
        response = client.get(url, {})

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_no_identity_and_invalid_psk_returns_401(self):
        connection.set_schema_to_public()
        Tenant.objects.create(schema_name=f"acct{self.account_id}")
        url = reverse("group-list")
        client = APIClient()
        self.service_headers["HTTP_X_RH_RBAC_PSK"] = "xyz"
        response = client.get(url, **self.service_headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_no_identity_and_invalid_account_returns_404(self):
        connection.set_schema_to_public()
        Tenant.objects.create(schema_name=f"acct{self.account_id}")
        url = reverse("group-list")
        client = APIClient()
        self.service_headers["HTTP_X_RH_RBAC_ACCOUNT"] = "1212"
        response = client.get(url, **self.service_headers)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_no_identity_and_invalid_client_id_returns_401(self):
        connection.set_schema_to_public()
        Tenant.objects.create(schema_name=f"acct{self.account_id}")
        url = reverse("group-list")
        client = APIClient()
        self.service_headers["HTTP_X_RH_RBAC_CLIENT_ID"] = "bad-service"
        response = client.get(url, **self.service_headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_no_identity_and_valid_psk_client_id_and_account_returns_200(self):
        connection.set_schema_to_public()
        Tenant.objects.create(schema_name=f"acct{self.account_id}")
        url = reverse("group-list")
        client = APIClient()
        response = client.get(url, **self.service_headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)


class AccessHandlingTest(TestCase):
    """Tests against getting user access in the IdentityHeaderMiddleware."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.tenant = Tenant.objects.get(schema_name="test")
        except:
            cls.tenant = Tenant(schema_name="test")
            cls.tenant.save(verbosity=0)

        connection.set_tenant(cls.tenant)

    @classmethod
    def tearDownClass(cls):
        connection.set_schema_to_public()
        cls.tenant.delete()

    def test_no_principal_found(self):
        expected = {
            "group": {"read": [], "write": []},
            "role": {"read": [], "write": []},
            "policy": {"read": [], "write": []},
        }
        access = IdentityHeaderMiddleware._get_access_for_user()
        self.assertEqual(expected, access)

    def test_principal_no_access(self):
        """Test access for existing principal with no access definitions."""
        Principal.objects.create(username="test_user")
        expected = {
            "group": {"read": [], "write": []},
            "role": {"read": [], "write": []},
            "policy": {"read": [], "write": []},
        }
        access = IdentityHeaderMiddleware._get_access_for_user()
        self.assertEqual(expected, access)

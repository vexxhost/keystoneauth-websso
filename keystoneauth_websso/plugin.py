# coding=utf-8

# Copyright 2016 Spanish National Research Council
# Copyright 2016 INDIGO-DataCloud
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import cgi
import json
import os
import re
import socket
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from keystoneauth1 import _utils as utils
from keystoneauth1.identity.v3 import federation

from keystoneauth_websso import exceptions

_logger = utils.get_logger(__name__)


class _ClientCallbackServer(HTTPServer):
    """HTTP server to handle the OpenID Connect callback to localhost.

    This server will wait for a single request, storing the access_token
    obtained from the incoming request into the 'token' attribute.
    """

    token = None

    def server_bind(self):
        """Override original bind and set a timeout.

        Authentication may fail and we could get stuck here forever, so this
        method sets up a sane timeout.
        """
        # NOTE(aloga): cannot call super here, as HTTPServer does not have
        # object as an ancestor
        HTTPServer.server_bind(self)
        self.socket.settimeout(60)


class _ClientCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the OpenID Connect redirect callback.

    The OpenID Connect authorization code grant type is a redirection based
    flow where the client needs to be capable of receiving incoming requests
    (via redirection), where the access code will be obtained.

    This class implements a request handler that will process a single request
    and store the obtained code into the server's 'code' attribute
    """

    def do_POST(self):
        """Handle a POST request and obtain an authorization code.

        This method will process the query parameters and get the
        cookies from the completed mod_auth_openid session
        """
        postvars = {}
        # we specifically need the mod_auth_openidc cookies but we will pass store all headers for now

        if self.headers:

            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers["Content-Type"],
                },
            )

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><head><title>Authentication Status OK</title></head>"
                b"<body><p>The authentication flow has been completed.</p>"
                b"<p>You can close this window.</p>"
                b"</body></html>"
            )

            for field in form.keys():
                field_item = form[field]
                if not field_item.filename:
                    # Regular Form Value
                    postvars[field] = form[field].value

            self.server.token = postvars["token"]
        else:
            self.send_response(501)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><head><title>Authentication Status Failed</title></head>"
                b"<body><p>The authentication flow failed.</p>"
                b"<p>You can close this window.</p>"
                b"</body></html>"
            )


def _wait_for_token(redirect_host, redirect_port):
    """Spawn an HTTP server and wait for the auth_token.

    :param redirect_host: The hostname where the authorization request will
                            be redirected. This normally is localhost. This
                            indicates the hostname where the callback http
                            server will listen.
    :type redirect_host: string

    :param redirect_port: The port where the authorization request will
                            be redirected. This indicates the port where the
                            callback http server will bind to.
    :type redirect_port: int
    """
    server_address = (redirect_host, redirect_port)
    try:
        httpd = _ClientCallbackServer(server_address, _ClientCallbackHandler)
    except socket.error:
        _logger.error(
            "Cannot spawn the callback server on port "
            "%s, please specify a different port." % redirect_port
        )
        raise

    # This will trigger _ClientCallbackHandler
    httpd.handle_request()
    httpd.server_close()

    if httpd.token:
        return httpd.token
    else:
        raise exceptions.MissingToken


class OpenIDConnect(federation.FederationBaseAuth):
    """Implementation for OpenID Connect authentication."""

    def __init__(
        self,
        auth_url,
        identity_provider,
        protocol,
        redirect_host="localhost",
        redirect_port=9990,
        cache_path=os.environ.get("HOME") + "/.cache/",
        **kwargs
    ):
        """The OpenID Connect plugin expects the following arguments.

        :param redirect_host: The hostname where the authorization request will
                              be redirected. This normally is localhost. This
                              indicates the hostname where the callback http
                              server will listen.
        :type redirect_host: string

        :param redirect_port: The port where the authorization request will
                              be redirected. This indicates the port where the
                              callback http server will bind to.
        :type redirect_port: int
        """
        super(OpenIDConnect, self).__init__(
            auth_url, identity_provider, protocol, **kwargs
        )
        self.cache_path = cache_path
        self.redirect_host = redirect_host
        self.redirect_port = int(redirect_port)
        self.redirect_uri = "http://%s:%s/auth/websso/" % (
            self.redirect_host,
            self.redirect_port,
        )

    @property
    def federated_token_url(self):
        """URL where websso auth flow is started."""
        host = self.auth_url.rstrip("/")
        if not host.endswith("v3"):
            host += "/v3"
        values = {
            "host": host,
            "identity_provider": self.identity_provider,
            "protocol": self.protocol,
        }
        url = (
            "%(host)s/auth/OS-FEDERATION/identity_providers/"
            "%(identity_provider)s/protocols/%(protocol)s/websso"
        )
        url = url % values

        return url

    def _get_auth_token(self):
        """Spawn a browser session to start the authentication process. The
        user will be redirected to identity provider to sign in.  Then a token
        will be generated and returned.

        :returns auth_token
        """
        webbrowser.open(
            self.federated_token_url + "?origin=" + self.redirect_uri, new=0
        )

        return _wait_for_token(self.redirect_host, self.redirect_port)

    def _get_token_metadata(self, session, auth_token):
        """Use the keystone auth_token to get the token metadata such as expiresAt

        :param obj session: keystoneauth1.session.Session
        :param str auth_token: the auth_token

        Returns:
            auth_response: response to a GET that includes keystone token metadata
        """

        headers = {"X-Auth-Token": auth_token, "X-Subject-Token": auth_token}

        return session.get(
            self.auth_url + "/auth/tokens", headers=headers, authenticated=False
        )

    def get_unscoped_auth_ref(self, session):
        """Authenticate with OpenID Connect Identity Provider.

        This is a multi-step process:

        1. Send user to a webbrowser to authenticate. User will be redirected to a
           local webserver so a auth_token can be captured

        2. Use the auth_token to get additional token metadata

        3. Cache token data and use set_auth_state method to set an auth_ref
           to be used to get an rescoped token based on user settings

        Note: Cache filename is based on auth_url and identity_provider only
        as an unscoped token can then be cached for the user.

        :param session: a session object to send out HTTP requests.
        :type session: keystoneauth1.session.Session

        :returns: a token data representation
        :rtype: :py:class:`keystoneauth1.access.AccessInfoV3`
        """
        cached_data = self.get_cached_data()

        if cached_data:
            self.set_auth_state(cached_data)

        if self.auth_ref is None:
            # Start Auth Process and get Keystone Auth Token
            auth_token = self._get_auth_token()

            # Use auth token to get token metadata
            response = self._get_token_metadata(session, auth_token)

            # Cache token and token metadata
            data = json.dumps({"auth_token": auth_token, "body": response.json()})
            self.put_cached_data(data)

            # Set auth_ref
            self.set_auth_state(data)

        return self.auth_ref

    def get_cached_data(self):
        """Get cached token"""
        cache_path = self._get_cache_path()

        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not self._token_expired(data):
                return data

    def put_cached_data(self, data):
        """Write cache data to file"""
        if not os.path.exists(self.cache_path):
            os.mkdirs(self.cache_path)

        with open(self._get_cache_path(), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _get_cache_path(self):
        """Retrieve the location of the session cache

        :returns a string of the path for the appropriate cache file
        """
        return self.cache_path + self.get_cache_id()

    def get_cache_id(self):
        """slugifys the auth_url and identity provider for use as cache filename"""
        return "os-" + re.sub(
            "[^A-Za-z0-9-]+", "-", self.auth_url + "-" + self.identity_provider
        )

    def _token_expired(self, data):
        """Check to see if the token is expired

        Args:
            data (str): expiration date from current token cache

        :returns True or False
        :rtype   bool
        """
        _data = json.loads(data)

        expiration = datetime.strptime(
            _data["body"]["token"]["expires_at"], "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        now = datetime.now()
        if expiration < now:
            return True
        else:
            return False

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

import socket
import webbrowser
import os
import json
from urllib.parse import urlparse, parse_qs
from keystoneauth1 import _utils as utils
from keystoneauth1 import access
from keystoneauth1.identity.v3 import oidc
from positional import positional
from http.server import BaseHTTPRequestHandler, HTTPServer
from keystoneauth_openid import exceptions
import cgi

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
        #we specifically need the mod_auth_openidc cookies but we will pass store all headers for now

        if self.headers:

            form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={'REQUEST_METHOD': 'POST',
                            'CONTENT_TYPE': self.headers['Content-Type'],
                            })


            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><head><title>Authentication Status OK</title></head>"
                b"<body><p>The authentication flow has been completed.</p>"
                b"<p>You can close this window.</p>"
                b"</body></html>")

            for field in form.keys():
                field_item = form[field]
                if field_item.filename:
                    file_data = field_item.file.read()
                    file_len = len(file_data)
                    del file_data
                    response = '\tUploaded {} as {!r} ({} bytes\n'.format(field, field_item.filename, file_len)
                else:
                    # Regular Form Value
                    postvars[field] = form[field].value
                    response = '\t{}={}\n'.format(field, form[field].value)

            self.server.token = postvars['token']
        else:
            self.send_response(501)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><head><title>Authentication Status Failed</title></head>"
                b"<body><p>The authentication flow failed.</p>"
                b"<p>You can close this window.</p>"
                b"</body></html>")

def _wait_for_token(redirect_host, redirect_port):
    """Spawn an HTTP server and wait for the auth id_token.

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
        httpd = _ClientCallbackServer(server_address,
                                      _ClientCallbackHandler)
    except socket.error:
        _logger.error("Cannot spawn the callback server on port "
                      "%s, please specify a different port." %
                      redirect_port)
        raise

    # This will trigger _ClientCallbackHandler
    httpd.handle_request()
    httpd.server_close()

    if httpd.token:
        return httpd.token
    else:
        raise exceptions.MissingOidcSessionHeaders


class OpenIDConnect(oidc._OidcBase):
    """Implementation for OpenID Connect authentication."""
    @positional(3)
    def __init__(self, auth_url, identity_provider, protocol,
                 client_id='keystone', client_secret='dummy',
                 access_token_type='access_token',
                 redirect_host="localhost", redirect_port=9990,
                 cache_path=os.environ.get('HOME') + '/.cache/keystone_cache',
                 **kwargs):
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
        super(OpenIDConnect, self).__init__(auth_url, identity_provider, protocol,
                                            client_id, client_secret,
                                            access_token_type, cache_path,
                                            **kwargs)
        self.cache_path = cache_path
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token_type = access_token_type
        self.redirect_host = redirect_host
        self.redirect_port = int(redirect_port)
        self.redirect_uri = "http://%s:%s" % (self.redirect_host,
                                              self.redirect_port)

    @property
    def federated_auth_url(self):
        """Full URL where authorization data is sent."""
        values = {
            'host': self.auth_url.rstrip('/'),
            'identity_provider': self.identity_provider,
            'protocol': self.protocol
        }
        url = ("%(host)s/OS-FEDERATION/identity_providers/"
               "%(identity_provider)s/protocols/%(protocol)s/auth")

        url = url % values

        return url

    @property
    def federated_token_url(self):
        """Full URL where authorization data is sent."""
        host = self.auth_url.rstrip('/')
        if not host.endswith('v3'):
            host += '/v3'
        values = {
            'host': host,
            'identity_provider': self.identity_provider,
            'protocol': self.protocol
        }
        url = ("%(host)s/auth/OS-FEDERATION/identity_providers/"
               "%(identity_provider)s/protocols/%(protocol)s/websso")
        url = url % values

        return url

    def get_redirect_location(self, session):
        """Start the authentication session with keystone so we get session
        cookies since we will need to do an out-of-band auth process

        :param obj session: keystoneauth1.session.Session

        :returns:   location - where usere will enter their credentials
                    cookie - specifically need the auth_session_id
        """
        location = None
        # We need to initiate the first request without following redirects so we can get the needed
        # login page to use in the webbrowser session
        response = session.get(self.federated_token_url + "?origin=" + self.redirect_uri,
                                    redirect=False,
                                     authenticated=False,)
        location = response.headers["Location"] # redirects back to keystone before redirecting local

        return location

    def _get_access_token(self, location):
        """Spawn a browser session to continue the authentication process. The

        The response we get from keystone is used to create our access token
        keystoneauth1.access.access.create()

        :param str login_page: the URI from the `location` header of the
                                keystone redirect

        :returns access_token and session cookies in the headers
        """
        webbrowser.open(location, new=0)
        # Since we initiated the auth request via Keystone we will have the
        # OIDC session cookies in the headers from mod_auth_openidc.  We need
        # to complete the authentication to get the keystone token

        token = _wait_for_token(self.redirect_host, self.redirect_port)
        return token


    def _get_keystone_token(self, session, token):
        """Exchange the access_token for a keystone token

        :param obj session: keystoneauth1.session.Session
        :param str token: the token headers containing the mod_auth_openidc
                            session that was completed in the previous step.

        Returns:
            auth_response: response to a GET that includes keystone token
        """

        headers = {'X-Auth-Token': token,
            'X-Subject-Token': token}

        auth_response = session.get(self.auth_url + '/auth/tokens',
                                     headers=headers,
                                     authenticated=False)
        return auth_response

    def get_payload(self, session):
        return super().get_payload(session)

    def get_unscoped_auth_ref(self, session):
    # def get_auth_ref(self, session):
        """Authenticate with OpenID Connect and get back claims.

        This is a multi-step process:

        1.- We need to establish the login page to open an browser to complete
            a full openID session and retrieve an access_token from keystone.

        2.- Use this access_token to obtain our keystone token

        3.- Pass the token response to the session.create() to esablish our session

        :param session: a session object to send out HTTP requests.
        :type session: keystoneauth1.session.Session

        :returns: a token data representation
        :rtype: :py:class:`keystoneauth1.access.AccessInfoV3`
        """
        cached_data = self.get_auth_state()
        if  cached_data is None:
            # We need to initiate the auth to keystone to get the location header
            # in order to spawn our web browser.
            location = self.get_redirect_location(session)
            # Now obtain the access token from the OIDC provider
            cookies = self._get_access_token(location) # rename to tokens

            response = self._get_keystone_token(session, cookies)

            self.auth_ref = access.create(resp=response)

            self.set_auth_state(self.auth_ref.auth_token)
        else:
            self.set_auth_state(cached_data)

        return self.auth_ref

    def set_auth_state(self, data):

        if 'body' in data:
            jdata = data
        else:
            data = {'auth_token': data,
                    'body': self.auth_ref._data}

            jdata = json.dumps(data)

        with open(self.cache_path, 'w', encoding='utf-8') as f:
            json.dump(jdata, f)

        return super().set_auth_state(jdata)


    def get_auth_state(self):
        # TODO: Check expiration
        if os.path.exists(self.cache_path):
            with open(self.cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        return super().get_auth_state()

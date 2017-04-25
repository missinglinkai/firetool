# coding=utf-8
import base64
import copy
import json
import os
import urlparse
from urllib import urlencode
import datetime
import marshal

import logging

import httplib2
from oauth2client.client import Credentials, AccessTokenRefreshError

EXPIRY_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


class GITCredentials(Credentials):
    def __init__(self, custom_token_creator=None, api_key=None, access_token=None, refresh_token=None,
                 token_expiry=None):
        api_key = api_key or os.environ['GOOGLE_ID_TOOLKIT_KEY']
        self.custom_token_creator = custom_token_creator

        self.store = None
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expiry = token_expiry
        self.api_key = api_key
        self.invalid = False

        super(GITCredentials, self).__init__()

    def to_json(self):
        old_code_serialized = marshal.dumps(self.custom_token_creator.func_code)
        custom_token_creator = base64.b64encode(old_code_serialized)
        data = json.loads(self._to_json(['store', 'custom_token_creator']))

        data['custom_token_creator'] = custom_token_creator

        return json.dumps(data)

    @property
    def token_uri(self):
        return "https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyCustomToken?key={0}".format(
            self.api_key)

    @classmethod
    def from_json(cls, s):
        data = json.loads(s)
        if 'token_expiry' in data and not isinstance(data['token_expiry'], datetime.datetime):
            try:
                data['token_expiry'] = datetime.datetime.strptime(data['token_expiry'], EXPIRY_FORMAT)
            except:
                data['token_expiry'] = None

        custom_token_creator = base64.b64decode(data["custom_token_creator"])

        credentials = GITCredentials(
            marshal.loads(custom_token_creator),
            api_key=data["api_key"],
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            token_expiry=data["token_expiry"])

        credentials.invalid = data["invalid"]

        return credentials

    @property
    def access_token_expired(self):
        if self.invalid:
            return True

        if not self.token_expiry:
            return False

        now = datetime.datetime.utcnow()
        if now >= self.token_expiry:
            return True

        return False

    def set_store(self, store):
        self.store = store

    def _updateFromCredential(self, other):
        """Update this Credential from another instance."""
        self.__dict__.update(other.__getstate__())

    def __getstate__(self):
        d = copy.copy(self.__dict__)
        del d['store']
        return d

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.store = None

    def _generate_refresh_request_body(self):
        body = json.dumps({"returnSecureToken": True, "token": self.custom_token_creator()})
        return body

    @classmethod
    def _generate_refresh_request_headers(cls):
        headers = {"content-type": "application/json; charset=UTF-8"}
        return headers

    def _refresh(self, http_request):
        if not self.store:
            self._do_refresh_request(http_request)
            return

        self.store.acquire_lock()
        try:
            new_cred = self.store.locked_get()

            if new_cred and not new_cred.invalid and new_cred.access_token != self.access_token and not new_cred.access_token_expired:
                self._updateFromCredential(new_cred)
            else:
                self._do_refresh_request(http_request)
        finally:
            self.store.release_lock()

    def _do_refresh_request(self, http_request):
        body = self._generate_refresh_request_body()
        headers = self._generate_refresh_request_headers()

        resp, content = http_request(
            self.token_uri, method='POST', body=body, headers=headers)

        if resp.status == 200:
            d = json.loads(content)
            self.access_token = d['idToken']
            self.refresh_token = d.get('refreshToken', self.refresh_token)
            if 'expiresIn' in d:
                self.token_expiry = datetime.timedelta(
                    seconds=int(d['expiresIn'])) + datetime.datetime.utcnow()
            else:
                self.token_expiry = None

            if self.store:
                self.store.locked_put(self)
        else:
            # An {'error':...} response body means the token is expired or revoked,
            # so we flag the credentials as such.
            error_msg = 'Invalid response %s.' % resp['status']
            d = json.loads(content)
            if 'error' in d:
                error_msg = d['error']
                self.invalid = True
                if self.store:
                    self.store.locked_put(self)

            raise AccessTokenRefreshError(error_msg)

    @classmethod
    def set_query_parameter(cls, url, param_name, param_value):
        scheme, netloc, path, query_string, fragment = urlparse.urlsplit(url)
        query_params = urlparse.parse_qs(query_string)

        query_params[param_name] = [param_value]
        new_query_string = urlencode(query_params, doseq=True)

        return urlparse.urlunsplit((scheme, netloc, path, new_query_string, fragment))

    def authorize(self, http):
        request_orig = http.request

        # The closure that will replace 'httplib2.Http.request'.
        def new_request(
                uri, method='GET', body=None, headers=None,
                redirections=httplib2.DEFAULT_MAX_REDIRECTS,
                connection_type=None):
            if not self.access_token or self.access_token_expired:
                self._refresh(request_orig)

            # Modify the request headers to add the appropriate
            # Authorization header.
            if headers is None:
                headers = {}

            uri = self.set_query_parameter(uri, 'auth', self.access_token)

            resp, content = request_orig(uri, method, body, headers,
                                         redirections, connection_type)

            if resp.status == 401:
                logging.info("got 401 refreshing token")
                self._refresh(request_orig)
                uri = self.set_query_parameter(uri, 'auth', self.access_token)
                return request_orig(uri, method, body, headers, redirections, connection_type)
            else:
                return resp, content

        http.request = new_request
        return http

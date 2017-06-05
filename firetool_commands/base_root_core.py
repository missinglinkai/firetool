# coding=utf-8
import json
import logging
import math

try:
    import httplib
except ImportError:
    import http.client as httplib

try:
    from urlparse import urljoin
except ImportError:
    from urllib.parse import urljoin


def _json_handler(obj):
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()

    if math.isnan(obj):
        return None

    if math.isinf(obj):
        return None

    raise TypeError('Object of type %s with value of %s is not JSON serializable' % (type(obj), repr(obj)))


class FirebaseRootCore(object):
    gets = 0

    def __init__(self, firebase_root):
        self._http = None
        self._firebase_root = firebase_root

    def get_http(self):
        return None

    @property
    def http(self):
        if self._http is None:
            self._http = self.get_http()
            self._http.timeout = 60

        return self._http

    def set_credentials(self, credentials):
        self._http = credentials.authorize(self.http)

    @classmethod
    def common_path(cls, a, b):
        a_elements = a.split('/')
        b_elements = b.split('/')
        shared = []
        for i in range(min(len(a_elements), len(b_elements))):
            if a_elements[i] == b_elements[i]:
                shared.append(b_elements[i])
                continue

            break

        return "/".join(shared)

    @classmethod
    def subtract_path(cls, common_path, path):
        p = path.replace(common_path, '')

        if p.startswith('/'):
            p = p[1:]

        return p

    def firebase_root(self):
        return self._firebase_root

    @classmethod
    def validate_http_response(cls, response, content):
        if response.status >= 400:
            logging.error("request failed %d %s", response.status, content)
            raise httplib.HTTPException(content)

    def on_request(self, url, method, body, headers):
        if method == 'NOPE':
            return {}

        res, content = self.http.request(url, method=method, body=body, headers=headers)
        self.validate_http_response(res, content)

        return json.loads(content.decode('utf8'))

    def _json_method_url(self, method, path, params):
        url = self.build_url(path)

        body = None
        headers = None

        if method != 'GET':
            json_str = json.dumps(params, default=_json_handler)
            body = json_str
            headers = {"Content-Type": "application/json"}
        elif 'shallow' in params:
            shallow = params.get('shallow')
            del params['shallow']

            if shallow:
                url += '?shallow=true'

        try:
            r = self.on_request(url, method, body, headers)
        except httplib.HTTPException:
            logging.error("The following request failed: (%s) %s\nbody: %s\nheaders: %s", method, url, body, headers)
            raise

        return r

    def json_method(self, method, *args, **kwargs):
        if kwargs or method == 'GET':
            url = self.build_path(*args)
            return self._json_method_url(method, url, kwargs)
        else:
            url = self.build_path(*args[:-1]) if len(args) > 1 else self.build_path(*args)
            return self._json_method_url(method, url, args[-1])

    def get(self, *args, **kwargs):
        post_process = kwargs.get('post_process')
        result = self.json_method("GET", *args, **kwargs)

        if post_process is None:
            return result

        return post_process(result)

    def put(self, *args, **kwargs):
        return self.json_method("PUT", *args, **kwargs)

    def delete(self, *args, **kwargs):
        return self.json_method("DELETE", *args, **kwargs)

    def nope(self, *args, **kwargs):
        return self.json_method("NOPE", *args, **kwargs)

    def multi_patch(self, url, params):
        return self._json_method_url("PATCH", url, params)

    def patch(self, *args, **kwargs):
        return self.json_method("PATCH", *args, **kwargs)

    @classmethod
    def subtract_paths(cls, d, common_path):
        return {cls.subtract_path(common_path, k): v for k, v in d.items()}

    def build_url(self, *args):
        path = self.build_path(*args)

        if path.endswith(".json"):
            return path

        return path + "/.json"

    def build_path(self, *args):
        path = self.firebase_root()

        for arg in args[:-1]:
            path = urljoin(path, str(arg))
            path += "/"

        path = urljoin(path, str(args[-1]))

        if path.endswith("/"):
            path = path[:-1]

        return path

    def flatten_data(self, big_patch, path, common_path, current_data, current_path=None):
        for k, v in current_data.items():
            key_current_path = (current_path or [])[:]
            key_current_path.append(k)

            if isinstance(v, dict):
                self.flatten_data(big_patch, path, common_path, v, key_current_path)
                continue

            path_with_key = self.build_path(path, *key_current_path)
            big_patch[self.subtract_path(common_path, path_with_key)] = v

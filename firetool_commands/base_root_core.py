# coding=utf-8
import abc
import json
import math
import dateutil.parser

import six
from six.moves.urllib.parse import urljoin, urlencode

try:
    import httplib
except ImportError:
    import http.client as httplib


def _json_handler(obj):
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()

    if math.isnan(obj):
        return None

    if math.isinf(obj):
        return None

    raise TypeError('Object of type %s with value of %s is not JSON serializable' % (type(obj), repr(obj)))


@six.add_metaclass(abc.ABCMeta)
class HttpRootCore(object):
    def __init__(self, api_root):
        self._http = None
        self._api_root = api_root

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

    @abc.abstractmethod
    def _get(self, *args, **kwargs):
        """

        :param args:
        :param kwargs:
        :return:
        """

    @abc.abstractmethod
    def _get_document(self, *args, **kwargs):
        """

        :param args:
        :param kwargs:
        :return:
        """

    @abc.abstractmethod
    def _put(self, path, value, **kwargs):
        """

        :param args:
        :param kwargs:
        :return:
        """

    def put(self, path, value, **kwargs):
        return self._put(path, value, **kwargs)

    def get(self, *args, **kwargs):
        post_process = kwargs.get('post_process')

        result = self._get(*args, **kwargs)

        if post_process is None:
            return result

        return post_process(result)

    def get_document(self, *args, **kwargs):
        post_process = kwargs.get('post_process')

        result = self._get_document(*args, **kwargs)

        if post_process is None:
            return result

        return post_process(result)

    def build_path(self, *args):
        path = self.api_root()

        for arg in args[:-1]:
            path = urljoin(path, str(arg))
            path += "/"

        path = urljoin(path, str(args[-1]))

        if path.endswith("/"):
            path = path[:-1]

        return path

    def api_root(self):
        return self._api_root


class FirestoreRootCore(HttpRootCore):
    def _put(self, path, value, **kwargs):
        path, field = path.rsplit('/', 1)
        url = self.build_path(path)

        value_type = None
        if isinstance(value, six.string_types):
            value_type = 'stringValue'
        elif isinstance(value, bool):
            value_type = 'booleanValue'

        if value_type is None:
            raise Exception('Unknown type %s' % (type(value)))

        body = {
            'fields': {
                field: {value_type: value}
            }
        }

        params = {
            'updateMask.fieldPaths': field
        }

        headers = {'Content-type': 'application/json'}

        r = self.on_request(url, 'PATCH', json.dumps(body), params=params, headers=headers)

        return r

    @classmethod
    def _convert_val(cls, val_type, val_value):
        if val_type == 'stringValue':
            return val_value

        if val_type == 'timestampValue':
            return dateutil.parser.parse(val_value)

        if val_type == 'integerValue':
            return int(val_value)

        if val_type == 'doubleValue':
            return float(val_value)

        if val_type == 'arrayValue':
            return [cls._convert_val(item.keys()[0], item.values()[0]) for item in val_value.get('values')]

        if val_type == 'nullValue':
            return None

        if val_type == 'booleanValue':
            return bool(val_value)

        if val_type == 'mapValue':
            return cls._native_dict(val_value.get('fields'))

        raise Exception('unknown type {val_type}'.format(val_type=val_type))

    @classmethod
    def _native_dict(cls, d):
        result = {}
        for key, val in d.items():
            for val_type, val_value in val.items():
                result[key] = cls._convert_val(val_type, val_value)

        return result

    def _get_document(self, *args, **kwargs):
        url = self.build_path(*args)

        r = self.on_request(url, 'GET')

        return self._native_dict(r.get('fields'))

    def _get(self, *args, **kwargs):
        url = self.build_path(*args)

        def get_child_name(doc):
            name = doc['name']

            name = 'https://firestore.googleapis.com/v1/' + name

            return name[len(url) + 1:]

        documents = []

        page_token = None
        while True:
            params = {
                'mask.fieldPaths': 'name',
                'pageSize': 100,
            }

            if page_token is not None:
                params['pageToken'] = page_token

            r = self.on_request(url, 'GET', params=params)

            documents.extend(r.get('documents', []))
            page_token = r.get('nextPageToken')

            if page_token is None:
                break

        key_names = map(get_child_name, documents)

        return key_names

    @classmethod
    def validate_http_response(cls, response, content):
        if response.status >= 400:
            raise httplib.HTTPException(content, response)

    def on_request(self, url, method, body=None, headers=None, params=None):
        if method == 'NOPE':
            return {}

        if params:
            url = '%s?%s' % (url, urlencode(params))

        res, content = self.http.request(url, method=method, body=body, headers=headers)
        self.validate_http_response(res, content)

        return json.loads(content.decode('utf8'))


class FirebaseRootCore(HttpRootCore):
    gets = 0

    def build_url(self, *args):
        path = self.build_path(*args)

        if path.endswith(".json"):
            return path

        return path + "/.json"

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

    def flatten_data(self, big_patch, path, common_path, current_data, current_path=None):
        for k, v in current_data.items():
            key_current_path = (current_path or [])[:]
            key_current_path.append(k)

            if isinstance(v, dict):
                self.flatten_data(big_patch, path, common_path, v, key_current_path)
                continue

            path_with_key = self.build_path(path, *key_current_path)
            big_patch[self.subtract_path(common_path, path_with_key)] = v

    def json_method(self, method, *args, **kwargs):
        if kwargs or method == 'GET':
            url = self.build_path(*args)
            return self._json_method_url(method, url, kwargs)
        else:
            url = self.build_path(*args[:-1]) if len(args) > 1 else self.build_path(*args)
            return self._json_method_url(method, url, args[-1])

    def _get(self, *args, **kwargs):
        return self.json_method("GET", *args, **kwargs)

    _get_document = _get

    def _put(self, path, value, **kwargs):
        return self.json_method("PUT", path, value, **kwargs)

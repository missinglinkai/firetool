# coding=utf-8
import gevent
import re
import requests
from firetool_commands.base_root_core import FirebaseRootCore


def is_wildcard_element(element):
    return element.startswith('(')


def is_group_element(element):
    return element.startswith('{')


def is_spacial_element(element):
    return is_wildcard_element(element) or is_group_element(element)


class RequestsResponseWrapper(object):
    def __init__(self, r):
        self._r = r

    @property
    def status(self):
        return self._r.status_code


class RequestsWrapper(object):
    def __init__(self, firebase_root):
        self._firebase_root = firebase_root

    def request(self, url, method='GET', **kwargs):
        data = None
        if 'body' in kwargs:
            data = kwargs['body']
            del kwargs['body']

        if 'connection_type' in kwargs:
            del kwargs['connection_type']

        if 'redirections' in kwargs:
            del kwargs['redirections']

        rs = requests.request(method, url, data=data, **kwargs)

        return RequestsResponseWrapper(rs), rs.content


class PlainFirebaseRoot(FirebaseRootCore):
    def __init__(self, firebase_root):
        super(PlainFirebaseRoot, self).__init__(firebase_root)

    def get_http(self):
        return RequestsWrapper(self._firebase_root)


def get_elements(path):
    elements = path.split('/')

    results = []
    index = 0
    for element in elements:
        spacial_element = is_spacial_element(element)
        prev_spacial_element = len(results) > 0 and is_spacial_element(results[-1][0])

        if spacial_element or prev_spacial_element:
            index += 1

        if len(results) == index:
            results.append([])

        results[index].append(element)

    return ['/'.join(e) for e in results]


def return_final_result(method):
    new_futures = []
    for future_or_string in method():
        if isinstance(future_or_string, tuple):
            yield future_or_string
            continue

        new_futures.append(future_or_string)

    while len(new_futures) > 0:
        gevent.joinall(new_futures)
        current_futures = new_futures[:]
        new_futures = []
        for f in current_futures:
            for future_or_string in f.value:
                if isinstance(future_or_string, tuple):
                    yield future_or_string
                    continue

                new_futures.append(future_or_string)


def iterate_path(firebase_root, path):
    def inner(current_path, groups=None):
        elements = get_elements(current_path)

        if len(elements) == 0:
            return

        if len(elements) == 1:
            yield current_path, groups
            return

        start_path = elements[0]

        if is_wildcard_element(elements[1]):
            yield gevent.spawn(spawn_iterate, start_path, elements[:], groups)
            return

        if is_group_element(elements[1]):
            children_names = elements[1].replace('{', '').replace('}', '').split(',')

            for child_key in children_names:
                elements[1] = child_key

                for params in inner('/'.join(elements), groups):
                    yield params

    def spawn_iterate(start_path, elements, current_groups):
        children_names = firebase_root.get(start_path, shallow=True)

        if children_names is None:
            return

        pattern = elements[1]
        for child_key in children_names.keys():
            m = re.search(pattern, child_key)

            if m is None:
                continue

            elements[1] = child_key
            groups = current_groups or []
            groups.extend(m.groups())

            yield gevent.spawn(inner, '/'.join(elements), groups)

    for result in return_final_result(lambda: inner(path)):
        yield result


def join_or_raise(f, throw_exceptions=True):
    f.join()

    if f.exception:
        if throw_exceptions:
            raise f.exception
        else:
            return f.exception

    return f.value

# coding=utf-8
import types

import gevent
import re
import requests
from gevent.pool import Pool

from firetool_commands.base_root_core import FirebaseRootCore


def is_wildcard_element(element):
    return element.startswith('(')


def is_group_element(element):
    return element.startswith('{')


def group_element_to_children_keys(element):
    return element.replace('{', '').replace('}', '').split(',')


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
        self.pool = Pool(50)

    def get_http(self):
        return RequestsWrapper(self._firebase_root)

    def spawn(self, *args, **kwargs):
        return self.pool.spawn(*args, **kwargs)


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
        if future_or_string is None:
            continue

        if isinstance(future_or_string, tuple):
            yield future_or_string
            continue

        new_futures.append(future_or_string)

    while len(new_futures) > 0:
        gevent.wait(new_futures, count=1)
        ready_indexes = [i for i, ff in enumerate(new_futures) if ff.ready()]
        for i in ready_indexes:
            f = new_futures[i]
            new_futures[i] = None

            if f.value is None:
                continue

            if isinstance(f.value, gevent.Greenlet):
                new_futures.append(f.value)
                continue

            if not isinstance(f.value, types.GeneratorType):
                yield f.value
                continue

            for future_or_string in f.value:
                if isinstance(future_or_string, tuple):
                    yield future_or_string
                    continue
                elif isinstance(future_or_string, gevent.Greenlet):
                    new_futures.append(future_or_string)

        new_futures = [ff for ff in new_futures if ff is not None]


def fill_wildcards(p, groups):
    for i, g in enumerate(groups):
        p = p.replace('\{}'.format(i+1), g)

    return p


def no_op(val):
    return val


def natural_key(string_):
    return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', string_)]


def iterate_path(firebase_root, path, keys_only=False, condition=None, descending_order=False):
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
            is_leaf_element = len(elements) == 2

            if is_leaf_element and not keys_only:
                yield '/'.join(elements), groups
                return

            children_names = group_element_to_children_keys(elements[1])

            for child_key in children_names:
                elements[1] = child_key

                for params in inner('/'.join(elements), groups):
                    yield params

    def spawn_iterate(start_path, elements, current_groups):
        def wrap_return_child(elements, current_groups):
            def return_child(children_names):
                if children_names is None:
                    return

                pattern = elements[1]

                children_names = children_names.keys()

                children_names = sorted(children_names, reverse=descending_order, key=natural_key)

                for child_key in children_names:
                    m = re.search(pattern, child_key)

                    if m is None:
                        continue

                    elements[1] = child_key
                    groups = current_groups[:] if current_groups is not None else []
                    groups.extend(m.groups())

                    yield gevent.spawn(inner, '/'.join(elements), groups)

            return return_child

        yield firebase_root.spawn(firebase_root.get, start_path, shallow=True, post_process=wrap_return_child(elements, current_groups))

    def get_paths():
        for result_or_future in return_final_result(lambda: inner(path)):
            if condition is None:
                yield result_or_future
                continue

            _, current_groups = result_or_future

            def eval_and_get(path_condition_expended, result):
                condition_value = firebase_root.get(path_condition_expended)
                if condition_value is None:
                    return None

                return result

            condition_expended = fill_wildcards(condition, current_groups)

            yield gevent.spawn(eval_and_get, condition_expended, result_or_future)

    for result in return_final_result(lambda: get_paths()):
        yield result


def join_or_raise(f, throw_exceptions=True):
    f.join()

    if f.exception:
        if throw_exceptions:
            raise f.exception
        else:
            return f.exception

    return f.value

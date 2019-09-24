# coding=utf-8
import sys
import time
import datetime
import types
from contextlib import closing
import gevent
import re
import requests
from gevent.pool import Pool

from .base_root_core import FirebaseRootCore, FirestoreRootCore


def fill_wildcards(p, groups, values=None):
    for i, g in enumerate(groups or []):
        p = p.replace('\\{}'.format(i + 1), g)

    for name, value in (values or {}).items():
        if value is None:
            continue

        if '{%s}' % name not in p:
            continue

        p = p.replace('{%s}' % name, value)

    return p


class UpdateTimer(object):
    def __init__(self, interval=1.):
        self.__interval = interval
        self.__start_time = None

    def can_update(self):
        now = datetime.datetime.utcnow()
        if self.__start_time is None or (now - self.__start_time).total_seconds() > self.__interval:
            self.__start_time = now
            return True

        return False


class PrintStatus(object):
    def __init__(self, nl_on_clone=True, fp=sys.stdout):
        self.__update_timer = UpdateTimer()
        self.__first_status = True
        self.__last_printed_msg = None
        self.__last_msg = None
        self.__fp = fp
        self.__nl_on_close = nl_on_clone

    def close(self):
        if self.__last_msg is not None and self.__last_msg != self.__last_printed_msg:
            self.__print_status(True, self.__last_msg)

        if self.__nl_on_close:
            self.__print_to_out('\n')

    def __get_formatted_message(self, msg, *args, **kwargs):
        formatted_msg = ''

        if self.__last_printed_msg:
            spaces = len(self.__last_printed_msg)
            formatted_msg += '\r' + (' ' * spaces) + '\r'

        formatted_msg += msg.format(*args, **kwargs)

        if self.__first_status:
            formatted_msg = '\n' + formatted_msg

        return formatted_msg

    def __print_to_out(self, text):
        self.__fp.write(text)
        self.__fp.flush()

    def __print_status(self, force, msg, *args, **kwargs):
        formatted_msg = self.__get_formatted_message(msg, *args, **kwargs)

        self.__last_msg = formatted_msg.strip()

        if self.__update_timer.can_update() or force:
            self.__print_to_out(formatted_msg)
            self.__last_printed_msg = self.__last_msg

        return True

    def print_status(self, msg, *args, **kwargs):
        printed_status = self.__print_status(False, msg, *args, **kwargs)

        if self.__first_status and printed_status:
            self.__first_status = False


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

        while True:
            try:
                rs = requests.request(method, url, data=data, **kwargs)
                break
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
                time.sleep(2.0)
                continue

        return RequestsResponseWrapper(rs), rs.content


class PlainFirebaseRoot(FirebaseRootCore):
    def __init__(self, firebase_root):
        super(PlainFirebaseRoot, self).__init__(firebase_root)
        self.pool = Pool(50)

    def get_http(self):
        return RequestsWrapper(self._api_root)

    def spawn(self, *args, **kwargs):
        return self.pool.spawn(*args, **kwargs)


class PlainFirestoreRoot(FirestoreRootCore):
    def __init__(self, firebase_root):
        super(PlainFirestoreRoot, self).__init__(firebase_root)
        self.pool = Pool(50)

    def get_http(self):
        return RequestsWrapper(self._api_root)

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


def no_op(val):
    return val


def natural_key(string_):
    return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', string_)]


def iterate_path(firebase_root, path, keys_only=False, test_eval=None, descending_order=False):
    def inner(current_path, groups_with_progress=None):
        elements = get_elements(current_path)

        if len(elements) == 0:
            return

        if len(elements) == 1:
            yield current_path, groups_with_progress
            return

        start_path = elements[0]

        if is_wildcard_element(elements[1]):
            yield gevent.spawn(spawn_iterate, start_path, elements[:], groups_with_progress)
            return

        if is_group_element(elements[1]):
            is_leaf_element = len(elements) == 2

            if is_leaf_element and not keys_only:
                yield '/'.join(elements), groups_with_progress
                return

            children_names = group_element_to_children_keys(elements[1])

            for child_key in children_names:
                elements[1] = child_key

                for params in inner('/'.join(elements), groups_with_progress):
                    yield params

    def spawn_iterate(start_path, elements, current_groups_with_progress):
        def wrap_return_child(elements, current_groups_with_progress):
            def return_child(children_names):
                if children_names is None:
                    return

                pattern = elements[1]

                children_names = children_names.keys() if isinstance(children_names, dict) else children_names # TODO firebase needs to return a lsit

                children_names = sorted(children_names, reverse=descending_order, key=natural_key)

                for i, child_key in enumerate(children_names):
                    m = re.search(pattern, child_key)

                    if m is None:
                        continue

                    elements[1] = child_key
                    groups_with_progress = current_groups_with_progress[:] if current_groups_with_progress is not None else []
                    groups_with_progress.append((m.groups()[0], (i+1, len(children_names))))

                    yield gevent.spawn(inner, '/'.join(elements), groups_with_progress)

            return return_child

        yield firebase_root.spawn(firebase_root.get, start_path, shallow=True, post_process=wrap_return_child(elements, current_groups_with_progress))

    def get_paths():
        with closing(PrintStatus(fp=sys.stderr)) as print_status:
            for path_with_groups in return_final_result(lambda: inner(path)):
                current_root_path, groups_with_progress = path_with_groups

                if groups_with_progress:
                    status = current_root_path
                    for group_with_progress in groups_with_progress:
                        _, progress = group_with_progress
                        status += ' %s/%s' % progress

                    print_status.print_status(status)

                if test_eval is None:
                    yield path_with_groups
                    continue

                value = firebase_root.get(current_root_path)

                try:
                    if test_eval and not eval(test_eval, {}, value):
                        continue
                except TypeError:
                    print('%s: Error while eval value: %s' % (current_root_path, value,))
                    raise

                yield path_with_groups

    for result in return_final_result(get_paths):
        yield result


def join_or_raise(f, throw_exceptions=True):
    f.join()

    if f.exception:
        if throw_exceptions:
            raise f.exception
        else:
            return f.exception

    return f.value

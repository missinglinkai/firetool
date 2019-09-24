# coding=utf-8
import gevent
from .common import iterate_path, join_or_raise, is_group_element, group_element_to_children_keys, \
    fill_wildcards, no_op
from httplib import HTTPException


def get_and_join(firebase_root, path, child_keys, throw_exceptions=True):
    futures = []

    for key in child_keys:
        current_path = path + '/' + key
        f = firebase_root.spawn(firebase_root.get, current_path)
        futures.append(f)

    result = {}
    for key, future in zip(child_keys, futures):
        result[key] = join_or_raise(future, throw_exceptions=throw_exceptions)

    return result


class FirebaseOperators(object):
    @classmethod
    def firebase_get(cls, firebase_root, current_path, throw_exceptions=True):
        elements = current_path.split('/')

        last_element = elements[-1]
        if is_group_element(last_element):
            path = '/'.join(elements[:-1])
            return gevent.spawn(
                get_and_join, firebase_root, path, group_element_to_children_keys(last_element),
                throw_exceptions=throw_exceptions)
        else:
            return firebase_root.spawn(firebase_root.get, current_path)

    @classmethod
    def list_values(cls, firebase_root, root_path, throw_exceptions=True, shallow=False, keys_only=False,
                    descending_order=False, test_eval=None):
        def inner():
            for iterate_current_path, iterate_current_groups in iterate_path(
                    firebase_root, root_path, keys_only=keys_only, descending_order=descending_order,
                    test_eval=test_eval):

                def return_value():
                    if shallow or keys_only:
                        return {}

                    f = cls.firebase_get(firebase_root, iterate_current_path, throw_exceptions=throw_exceptions)
                    return join_or_raise(f, throw_exceptions)

                yield iterate_current_path, iterate_current_groups, return_value()

        for current_root_path, current_groups, value in inner():
            yield current_root_path, current_groups, value

    @classmethod
    def delete_values(cls, firebase_root, path, throw_exceptions=True, dry=False, test_eval=None):
        def delete_value(current_path):
            if not dry:
                firebase_root.delete(current_path)

            return current_path

        def create_futures():
            for iterate_current_path, iterate_current_groups in iterate_path(firebase_root, path, test_eval=test_eval):
                yield iterate_current_path, gevent.spawn(delete_value, iterate_current_path)

        for current_root_path, f in create_futures():
            try:
                val = join_or_raise(f)
            except HTTPException as ex:
                print('%s: %s' % (ex, current_root_path,))
                continue

            if not val:
                continue

            yield current_root_path, val

    @classmethod
    def count_values(cls, firebase_root, root_path, keys_only=False, descending_order=False):
        def inner():
            for iterate_current_path, iterate_current_groups in iterate_path(
                    firebase_root, root_path, keys_only=keys_only, descending_order=descending_order):

                total_keys = 0
                for _ in iterate_path(firebase_root, iterate_current_path + '/(.*)', keys_only=True):
                    total_keys += 1

                yield iterate_current_path, iterate_current_groups, total_keys

        for current_root_path, current_groups, counter in inner():
            yield current_root_path, counter

    @classmethod
    def copy_values(cls, firebase_root, src_path, dest_path, processor=None, dry=False, set_value=None, test_eval=None):
        def inner_copy_values():
            list_generator = cls.list_values(firebase_root, src_path, test_eval=test_eval)
            for current_path, current_groups_with_progress, val in list_generator:
                current_groups = [item for item, _ in current_groups_with_progress]
                if processor:
                    val = processor(current_path, val)

                dest_path_full = fill_wildcards(dest_path, current_groups, val)

                if set_value is not None:
                    val = fill_wildcards(set_value, current_groups, val)

                    if val:
                        if val.lower() == 'true':
                            val = True
                        elif val.lower() == 'false':
                            val = False

                if dry:
                    yield current_path, dest_path_full, gevent.spawn(no_op, val)
                    continue

                yield current_path, dest_path_full, firebase_root.spawn(firebase_root.put, dest_path_full, val)

        for root_path, groups, future in inner_copy_values():
            yield root_path, groups, join_or_raise(future)

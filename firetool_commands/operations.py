# coding=utf-8
import csv
import json
from httplib import HTTPException

import click
import gevent
import six

from firetool_commands.auth import get_firebase
from firetool_commands.common import iterate_path, join_or_raise, is_group_element, group_element_to_children_keys, \
    fill_wildcards, no_op


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


# noinspection PyUnusedLocal
def return_get_none(current_path):
    return gevent.spawn(no_op, None)


def firebase_get(firebase_root, current_path, throw_exceptions=True):
    elements = current_path.split('/')

    last_element = elements[-1]
    if is_group_element(last_element):
        path = '/'.join(elements[:-1])
        return gevent.spawn(
            get_and_join, firebase_root, path, group_element_to_children_keys(last_element),
            throw_exceptions=throw_exceptions)
    else:
        return firebase_root.spawn(firebase_root.get, current_path)


def list_values(firebase_root, root_path, throw_exceptions=True, shallow=False, keys_only=False,descending_order=False, test_eval=None):
    def inner():
        for iterate_current_path, iterate_current_groups in iterate_path(
                firebase_root, root_path, keys_only=keys_only, descending_order=descending_order, test_eval=test_eval):

            def return_value():
                if shallow or keys_only:
                    return {}

                f = firebase_get(firebase_root, iterate_current_path, throw_exceptions=throw_exceptions)
                return join_or_raise(f, throw_exceptions)

            yield iterate_current_path, iterate_current_groups, return_value()

    for current_root_path, current_groups, value in inner():
        yield current_root_path, current_groups, value


def delete_values(firebase_root, path, throw_exceptions=True, dry=False, test_eval=None):
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
            print('%s: %s' % (ex, current_root_path, ))
            continue

        if not val:
            continue

        yield current_root_path, val


def count_values(firebase_root, root_path, throw_exceptions=True, shallow=False, keys_only=False, condition=None, descending_order=False):
    def inner():
        for iterate_current_path, iterate_current_groups in iterate_path(
                firebase_root, root_path, keys_only=keys_only, condition=condition, descending_order=descending_order):

            total_keys = 0
            for _ in iterate_path(firebase_root, iterate_current_path + '/(.*)', keys_only=True):
                total_keys += 1

            yield iterate_current_path, iterate_current_groups, total_keys

    for current_root_path, current_groups, counter in inner():
        yield current_root_path, counter


def copy_values(firebase_root, src_path, dest_path, processor=None, dry=False, set_value=None, condition=None, test_eval=None):
    def inner_copy_values():
        list_generator = list_values(firebase_root, src_path, condition=condition, test_eval=test_eval)
        for current_path, current_groups, val in list_generator:
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


@click.group('op')
def operations_commands():
    pass


def write_csv_line(values):
    output = six.StringIO()
    writer = csv.writer(output)
    writer.writerow(values)

    click.echo(output.getvalue(), nl=False)


@click.command('count')
@click.option('--path', required=True)
@click.option('--project', '-p', required=True)
@click.option('--shallow/--no-shallow', default=False)
@click.option('--condition', required=False)
@click.option('--desc/--asc', required=False)
def count_command(path, project, shallow, condition, desc):
    firebase = get_firebase(project)

    for key, total_keys in count_values(firebase, path, throw_exceptions=False, shallow=shallow, condition=condition, descending_order=desc):
        click.echo('%s: %s' % (key, total_keys))


@click.command('list')
@click.option('--path', required=True)
@click.option('--project', '-p', required=True)
@click.option('--shallow/--no-shallow', default=False)
@click.option('--outputFormat', '-o', type=click.Choice(['json', 'csv']), default='json', required=False)
@click.option('--desc/--asc', required=False)
@click.option('--test-eval', required=False)
def list_command(path, project, shallow, outputformat, desc, test_eval):
    firebase = get_firebase(project)

    header_keys = None

    list_generator = list_values(firebase, path, throw_exceptions=False, shallow=shallow, descending_order=desc, test_eval=test_eval)
    for path, groups, value in list_generator:
        if value is None:
            continue

        if isinstance(value, Exception):
            continue

        if outputformat == 'csv':
            if header_keys is None:
                if isinstance(value, dict):
                    header_keys = value.keys()
                else:
                    header_keys = ['value']

                header_keys.insert(0, 'path')
                write_csv_line(header_keys)

            values = [path]
            if isinstance(value, dict):
                for key in header_keys[1:]:
                    values.append(value.get(key) or '')
            else:
                values.append(value)

            write_csv_line(values)
        else:
            data = {
                path: value,
            }

            click.echo(json.dumps(data))


@click.command('copy')
@click.option('--src', '-s', required=True)
@click.option('--dest', '-d', required=True)
@click.option('--project', '-p', required=True)
@click.option('--dry/--no-dry', default=False)
@click.option('--value', default=False)
@click.option('--condition', required=False)
@click.option('--test-eval', required=False)
def copy_command(src, dest, project, dry, value, condition, test_eval):
    copy_generator = copy_values(get_firebase(project), src, dest, dry=dry, set_value=value, condition=condition, test_eval=test_eval)
    for src, dest, value in copy_generator:
        if value is None:
            continue

        if isinstance(value, Exception):
            continue

        output_data = json.dumps(value)

        if len(output_data) > 1024:
            click.echo("%s => %s size: %s" % (src, dest, len(output_data)))
        else:
            click.echo("%s => %s %s" % (src, dest, output_data))


@click.command('delete')
@click.option('--path', required=True, multiple=True)
@click.option('--project', '-p', required=True)
@click.option('--dry/--no-dry', default=False)
@click.option('--test-eval', required=False)
def delete_command(path, project, dry, test_eval):
    for current_path in path:
        for deleted_path, value in delete_values(get_firebase(project), current_path, dry=dry, test_eval=test_eval):
            if isinstance(value, Exception):
                continue

            click.echo("delete %s" % deleted_path)

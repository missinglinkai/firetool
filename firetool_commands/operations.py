# coding=utf-8
import json
import click
import gevent
import six
from firetool_commands.auth import get_firebase
from firetool_commands.common import iterate_path, join_or_raise, is_group_element, group_element_to_children_keys


def get_and_join(firebase_root, path, child_keys, throw_exceptions=True):
    futures = []

    for key in child_keys:
        current_path = path + '/' + key
        f = gevent.spawn(firebase_root.get, current_path)
        futures.append(f)

    result = {}
    for key, future in zip(child_keys, futures):
        result[key] = join_or_raise(future, throw_exceptions=throw_exceptions)

    return result


def no_op(val):
    return val


# noinspection PyUnusedLocal
def return_get_none(firebase_root, current_path, current_groups, throw_exceptions=True):
    return current_path, current_groups, gevent.spawn(no_op, None)


def firebase_get(firebase_root, current_path, current_groups, throw_exceptions=True):
    elements = current_path.split('/')

    if is_group_element(elements[-1]):
        path = '/'.join(elements[:-1])
        return path, current_groups, gevent.spawn(
            get_and_join, firebase_root, path, group_element_to_children_keys(elements[-1]),
            throw_exceptions=throw_exceptions)
    else:
        return current_path, current_groups, gevent.spawn(firebase_root.get, current_path)


def display_values(firebase_root, root_path, throw_exceptions=True, shallow=False, keys_only=False):
    def inner():
        for current_path, current_groups in iterate_path(firebase_root, root_path, keys_only=keys_only):
            if shallow:
                yield current_path, current_groups, None
                continue

            gen_future = return_get_none if keys_only else firebase_get

            current_path, current_groups, future = gen_future(
                firebase_root, current_path, current_groups, throw_exceptions)

            yield current_path, current_groups, future

    futures = []
    for params in inner():
        futures.append(params)

        if len(futures) < 50:
            continue

        for root_path, groups, future in futures:
            yield root_path, groups, join_or_raise(future, throw_exceptions=throw_exceptions)

        futures = []

    for root_path, groups, future in futures:
        yield root_path, groups, join_or_raise(future, throw_exceptions=throw_exceptions)


def delete_values(firebase_root, path, dry=False):
    futures = []

    for p in iterate_path(firebase_root, path):
        if dry:
            future = gevent.spawn(no_op,  None)
        else:
            future = gevent.spawn(firebase_root.delete, p[0])

        futures.append((p[0], future))

    for p, f in futures:
        yield p, join_or_raise(f)


def copy_values(firebase_root, src_path, dest_path, processor=None, dry=False, set_value=None):
    def fill_wildcards(p, groups):
        for i, g in enumerate(groups):
            p = p.replace('\{}'.format(i+1), g)

        return p

    def no_op(val):
        return val

    keys_only = set_value is not None

    def inner_copy_values():
        for current_path, groups, val in display_values(firebase_root, src_path, keys_only=keys_only):
            if processor:
                val = processor(current_path, val)

            dest_path_full = fill_wildcards(dest_path, groups)

            if set_value is not None:
               val = fill_wildcards(set_value, groups)

            if dry:
                yield current_path, dest_path_full, gevent.spawn(no_op, val)
                continue

            yield current_path, dest_path_full, gevent.spawn(firebase_root.put, dest_path_full, val)

    futures = []
    for params in inner_copy_values():
        futures.append(params)

        if len(futures) < 50:
            continue

        for root_path, groups, future in futures:
            yield root_path, groups, join_or_raise(future)

        futures = []

    for root_path, groups, future in futures:
        yield root_path, groups, join_or_raise(future)


@click.group('op')
def operations_commands():
    pass


@operations_commands.command('list')
@click.pass_context
@click.option('--path', required=True)
@click.option('--project', '-p', required=True)
@click.option('--shallow/--no-shallow', default=False)
@click.option('--outputFormat', '-o', type=click.Choice(['json', 'csv']), default='csv', required=False)
def display_op(ctx, path, project, shallow, outputformat):
    def nice_string(d):
        if isinstance(d, six.string_types):
            return d

        if isinstance(d, six.integer_types):
            return d

        return json.dumps(value, indent=2, sort_keys=True)

    firebase = get_firebase(project)

    header_keys = None

    for path, groups, value in display_values(firebase, path, throw_exceptions=False, shallow=shallow):
        if value is None:
            continue

        if isinstance(value, Exception):
            continue

        if outputformat == 'csv':
            if header_keys is None:
                header_keys = value.keys()
                header_keys.insert(0, 'path')
                click.echo(','.join(header_keys))

            values = [path]
            for key in header_keys[1:]:
                values.append(value.get(key) or '')

            click.echo(','.join(values))
        else:
            click.echo("%s: %s" % (path, nice_string(value)))


@operations_commands.command('copy')
@click.pass_context
@click.option('--src', '-s', required=True)
@click.option('--dest','-d', required=True)
@click.option('--project', '-p', required=True)
@click.option('--dry/--no-dry', default=False)
@click.option('--value', default=False)
def copy_op(ctx, src, dest, project, dry, value):
    for src, dest, value in copy_values(get_firebase(project), src, dest, dry=dry, set_value=value):
        if value is None:
            continue

        if isinstance(value, Exception):
            continue

        output_data = json.dumps(value)

        if len(output_data) > 1024:
            click.echo("%s => %s size: %s" % (src, dest, len(output_data)))
        else:
            click.echo("%s => %s %s" % (src, dest, output_data))


@operations_commands.command('delete')
@click.pass_context
@click.option('--path', required=True)
@click.option('--project', '-p', required=True)
@click.option('--dry/--no-dry', default=False)
def delete_op(ctx, path, project, dry):
    for deleted_path, value in delete_values(get_firebase(project), path, dry=dry):
        if isinstance(value, Exception):
            continue

        click.echo("delete %s" % deleted_path)

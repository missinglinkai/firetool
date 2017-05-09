# coding=utf-8
import json
import click
import gevent
import six
from firetool_commands.auth import get_firebase
from firetool_commands.common import iterate_path, join_or_raise


def display_values(firebase_root, root_path, throw_exceptions=True, shallow=False, keys_only=False):
    def return_none():
        return None

    def inner():
        for current_path, current_groups in iterate_path(firebase_root, root_path):
            if shallow:
                yield current_path, current_groups, None
                continue

            if keys_only:
                yield current_path, current_groups, gevent.spawn(return_none)
            else:
                yield current_path, current_groups, gevent.spawn(firebase_root.get, current_path)

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
    def no_op(val):
        return val

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


@operations_commands.command('display')
@click.pass_context
@click.option('--path', required=True)
@click.option('--project', '-p', required=True)
@click.option('--shallow/--no-shallow', default=False)
def display_op(*args, **kwargs):
    path = kwargs['path']
    project = kwargs['project']
    shallow = kwargs['shallow']

    def nice_string(d):
        if isinstance(d, six.string_types):
            return d

        if isinstance(d, six.integer_types):
            return d

        return json.dumps(value, indent=2, sort_keys=True)

    firebase = get_firebase(project)

    for path, groups, value in display_values(firebase, path, throw_exceptions=False, shallow=shallow):
        if value is None:
            continue

        if isinstance(value, Exception):
            continue

        click.echo("%s: %s" % (path, nice_string(value)))


@operations_commands.command('copy')
@click.pass_context
@click.option('--src', '-s', required=True)
@click.option('--dest','-d', required=True)
@click.option('--project', '-p', required=True)
@click.option('--dry/--no-dry', default=False)
@click.option('--value', default=False)
def copy_op(*args, **kwargs):
    src_path = kwargs['src']
    dest_path = kwargs['dest']
    project = kwargs['project']
    dry = kwargs.get('dry')
    set_value = kwargs.get('value')

    for src_path, dest_path, value in copy_values(get_firebase(project), src_path, dest_path, dry=dry, set_value=set_value):
        if value is None:
            continue

        if isinstance(value, Exception):
            continue

        output_data = json.dumps(value)

        if len(output_data) > 1024:
            click.echo("%s => %s size: %s" % (src_path, dest_path, len(output_data)))
        else:
            click.echo("%s => %s %s" % (src_path, dest_path, output_data))


@operations_commands.command('delete')
@click.pass_context
@click.option('--path', required=True)
@click.option('--project', '-p', required=True)
@click.option('--dry/--no-dry', default=False)
def delete_op(*args, **kwargs):
    path = kwargs['path']
    project = kwargs['project']
    dry = kwargs.get('dry')

    for deleted_path, value in delete_values(get_firebase(project), path, dry=dry):
        if isinstance(value, Exception):
            continue

        click.echo("delete %s" % deleted_path)

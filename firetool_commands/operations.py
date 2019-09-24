# coding=utf-8
import csv
import json
import click
import gevent
import six

from .auth import get_firebase, get_firestore
from .common import no_op

# noinspection PyUnusedLocal
from .firebase_operators import FirebaseOperators


def return_get_none(current_path):
    return gevent.spawn(no_op, None)

def write_csv_line(values):
    output = six.StringIO()
    writer = csv.writer(output)
    writer.writerow(values)

    click.echo(output.getvalue(), nl=False)


@click.command('count')
@click.option('--use-firestore/--use-firebase',  is_flag=True)
@click.option('--path', required=True)
@click.option('--project', '-p', required=True)
@click.option('--desc/--asc', required=False)
def count_command(use_firestore, path, project, desc):
    db = get_firestore(project) if use_firestore else get_firebase(project)

    for key, total_keys in FirebaseOperators.count_values(db, path, descending_order=desc):
        click.echo('%s: %s' % (key, total_keys))


@click.command('list')
@click.option('--use-firestore/--use-firebase',  is_flag=True)
@click.option('--path', required=True)
@click.option('--project', '-p', required=True)
@click.option('--shallow/--no-shallow', default=False)
@click.option('--outputFormat', '-o', type=click.Choice(['json', 'csv']), default='json', required=False)
@click.option('--desc/--asc', required=False)
@click.option('--test-eval', required=False)
def list_command(use_firestore, path, project, shallow, outputformat, desc, test_eval):
    firebase = get_firebase(project)

    header_keys = None

    list_generator = FirebaseOperators.list_values(firebase, path, throw_exceptions=False, shallow=shallow, descending_order=desc, test_eval=test_eval)
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
@click.option('--use-firestore/--use-firebase', is_flag=True)
@click.option('--src', '-s', required=True)
@click.option('--dest', '-d', required=True)
@click.option('--project', '-p', required=True)
@click.option('--dry/--no-dry', default=False)
@click.option('--value', default=False)
@click.option('--test-eval', required=False)
def copy_command(use_firestore, src, dest, project, dry, value, test_eval):
    db = get_firestore(project) if use_firestore else get_firebase(project)

    copy_generator = FirebaseOperators.copy_values(db, src, dest, dry=dry, set_value=value, test_eval=test_eval)
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
@click.option('--use-firestore/--use-firebase',  is_flag=True)
@click.option('--path', required=True, multiple=True)
@click.option('--project', '-p', required=True)
@click.option('--dry/--no-dry', default=False)
@click.option('--test-eval', required=False)
def delete_command(use_firestore, path, project, dry, test_eval):
    for current_path in path:
        for deleted_path, value in FirebaseOperators.delete_values(get_firebase(project), current_path, dry=dry, test_eval=test_eval):
            if isinstance(value, Exception):
                continue

            click.echo("delete %s" % deleted_path)

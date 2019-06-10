#!/usr/bin/env python
# coding=utf-8
import click
from gevent import monkey
from firetool_commands import delete_command, copy_command, list_command, count_command

monkey.patch_all()


# noinspection PyUnusedLocal
@click.group()
def cli(**kwargs):
    pass


cli.add_command(delete_command)
cli.add_command(copy_command)
cli.add_command(list_command)
cli.add_command(count_command)


if __name__ == "__main__":
    cli()


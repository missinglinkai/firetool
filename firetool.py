# coding=utf-8
import click
from gevent import monkey
from firetool_commands import operations_commands

monkey.patch_all()


# noinspection PyUnusedLocal
@click.group()
def cli(**kwargs):
    pass


cli.add_command(operations_commands)


if __name__ == "__main__":
    cli()


# coding=utf-8
import os
from setuptools import setup, find_packages

build = os.environ['PIP_BUILD']
keywords = os.environ['PIP_KEYWORDS']


version = '0.{}'.format(build)

setup(
    name='firetool',
    version=version,
    py_modules=['firetool'],
    packages=find_packages(),
    install_requires=[
        'oauth2client',
        'gevent',
        'requests',
        'click',
    ],
    entry_points='''
        [console_scripts]
        firetool=firetool:cli
    ''',
)

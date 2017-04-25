# coding=utf-8
import json
import os
import random
import string
import tempfile


class XdgBadeDir(object):
    home = os.path.expanduser("~")

    data = os.environ.get('XDG_DATA_HOME', os.path.join(home, '.local', 'share') if home else None)
    config = os.environ.get('XDG_CONFIG_HOME', os.path.join(home, '.config') if home else None)
    cache = os.environ.get('XDG_CACHE_HOME', os.path.join(home, '.cache') if home else None)
    runtime = os.environ.get('XDG_RUNTIME_DIR')

    dataDirs = os.environ.get('XDG_DATA_DIRS', '/usr/local/share/:/usr/share/').split(':')

    if data:
        dataDirs.insert(0, data)

    configDirs = os.environ.get('XDG_CONFIG_DIRS', '/etc/xdg').split(':')

    if config:
        configDirs.insert(0, config)


def unique_string(l=32):
    return ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(l))


class Configstore(object):
    config_dir = XdgBadeDir.config or os.path.join(tempfile.gettempdir(), unique_string())

    def __init__(self, config_id, defaults=None, opts=None):
        opts = opts or {}
        defaults = defaults or {}
        path_prefix = os.path.join(config_id, 'config.json') if opts.get('globalConfigPath') else os.path.join(
            'configstore', '{id}.json'.format(id=config_id))

        self.path = os.path.join(self.config_dir, path_prefix)

        all_updated = self.all
        all_updated.update(defaults)
        self.all = all_updated

    @property
    def all(self):
        with open(self.path) as f:
            return json.load(f) or {}

    @all.setter
    def all(self, value):
        try:
            os.makedirs(os.path.dirname(self.path))
        except OSError as err:
            if err.errno != 17:
                raise

        with open(self.path, 'w') as f:
            json.dump(value, f, sort_keys=True, indent=4)

    @property
    def size(self):
        return len(self.all.keys())

    def __getitem__(self, key):
        keys = key.split('.')
        d = self.all
        for key in keys:
            d = d[key]

        return d

    def __setitem__(self, key, value):
        keys = key.split('.')
        d = self.all
        for key in keys[:-1]:
            d = d[key]

        d[keys[-1]] = value

    def has(self, key):
        keys = key.split('.')
        d = self.all
        for key in keys:
            if key not in d:
                return False

        return True

    def __delitem__(self, key):
        config = self.all

        keys = key.split('.')
        d = self.all
        for key in keys[:-1]:
            d = d[key]

        del d[keys[-1]]

    def clear(self):
        self.all = {}

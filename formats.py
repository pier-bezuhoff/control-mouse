import yaml
import os.path as op
from math import inf
from os import mkdir
from pynput import mouse, keyboard
from control_mouse.settings import parent_directory, options


class Storable:
    """Abstract class for smth to be stored at `path`,
    subclass `cls` should have cls.autosave_path, cls.directory and cls.extension"""
    def __init__(self, name=None, path=None):
        self.path = self.mk_path(name=name, path=path)

    @classmethod
    def name2path(cls, name):
        return op.join(cls.directory, name + cls.extension)

    @classmethod
    def mk_path(cls, name=None, path=None):
        if not name and not path:
            return cls.autosave_path
        elif name:
            return cls.name2path(name)
        else:
            return path

    @property
    def name(self):
        return op.splitext(op.split(self.path)[-1])[0]

    @name.setter
    def name(self, new_name):
        self.path = self.name2path(new_name)

    @property
    def filename(self):
        return op.split(self.path)[-1]

    @filename.setter
    def filename(self, new_filename):
        self.path = op.join(self.directory, new_filename)


class Record(Storable):
    "Record: [dict(action=str, **kwargs), ...]"
    directory = op.join(parent_directory, options.record_directory)
    if not op.exists(directory):
        mkdir(directory)
    extension = options.record_extension
    autosave = options.autosave
    autosave_name = options.autosave_record_name
    autosave_filename = autosave_name + extension
    autosave_path = op.join(directory, autosave_filename)

    def __init__(self, actions=None, name=None, path=None):
        Storable.__init__(self, name=name, path=path)
        self.actions = [] if actions is None else actions

    def __repr__(self):
        return "Record(actions=<x{}>, path={})".format(self.count, self.path)

    def __str__(self):
        return "<Record{} ({})>".format(" at '{}'".format(self.path) if self.path else "", pretty_dt(self.duration))

    @staticmethod
    def decrypt(action):
        if 'key' in action:
            key = action['key']
            if key.startswith("Key."):
                action['key'] = getattr(keyboard.Key, key[4:])
            elif key.startswith("Char."):
                action['key'] = keyboard.KeyCode.from_char(key[5:])
        if 'button' in action:
            button = action['button']
            if button.startswith("Button."):
                action['button'] = getattr(mouse.Button, button[7:])
        return action

    @staticmethod
    def from_yaml(actions):
        return list(map(Record.decrypt, actions))

    @staticmethod
    def load(name=None, path=None):
        path = Record.mk_path(name=name, path=path)
        with open(path) as file:
            actions = yaml.load(file)
        actions = Record.from_yaml(actions)
        record = Record(actions, path=path)
        print(record, "loaded")
        return record

    @staticmethod
    def encrypt(action):
        action = action.copy()
        if 'key' in action:
            key = action['key']
            if isinstance(key, keyboard.Key):
                action['key'] = "Key." + key.name
            elif isinstance(key, keyboard.KeyCode) and key.char:
                action['key'] = "Char." + key.char
        if 'button' in action:
            button = action['button']
            if isinstance(button, mouse.Button):
                action['button'] = "Button." + button.name
        return action

    def to_yaml(self):
        return list(map(Record.encrypt, self.actions))

    def save(self, name=None, path=None):
        actions = self.to_yaml()
        path = Record.mk_path(name=name, path=path)
        with open(path, 'w') as file:
            yaml.dump(actions, file)
        self.path = path
        print(str(self), "saved")

    @property
    def count(self):
        return len(self.actions)

    @property
    def duration(self):
        return sum(action['time'] for action in self.actions if action['action'] == 'wait')

    @duration.setter
    def duration(self, new_duration):
        ratio = new_duration / self.duration
        for action in self.actions:
            if action['action'] == 'wait':
                action['time'] *= ratio


class Sequence(Storable):
    "Sequence: [dict(record=Record[, repeat=<times>+<seconds>j][, speed=float]), ...]"
    directory = op.join(parent_directory, options.sequence_directory)
    if not op.exists(directory):
        mkdir(directory)
    extension = options.sequence_extension
    autosave = options.autosave
    autosave_name = options.autosave_sequence_name
    autosave_filename = autosave_name + extension
    autosave_path = op.join(directory, autosave_filename)

    def __init__(self, records=None, name=None, path=None):
        Storable.__init__(self, name=name, path=path)
        self.records = records or []

    @staticmethod
    def single(record):
        return Sequence([dict(record=record)])

    def __repr__(self):
        return "Sequence(records={}, path={})".format(self.records, self.path)

    def __str__(self):
        return "<Sequence of {} records{}>".format(len(self.records), " at '{}'".format(self.path) if self.path else "")

    @staticmethod
    def str2repeat(s):
        if not s:
            return 1
        elif s in ('∞', 'inf', 'oo'):
            return inf
        elif s.endswith('s'):
            return float(s[:-1]) * 1j
        else:
            return float(s)

    @staticmethod
    def str2speed(s):
        if not s:
            return 1
        elif s in ('∞', 'inf', 'oo'):
            return inf
        else:
            return float(s)
    
    @staticmethod
    def decrypt(record, cache={}):
        repeat, speed = record['repeat'], record['speed']
        # either 'record' in record or 'path' in record
        if 'path' in record:
            path = Record.mk_path(path=record.get('path', None), name=record.get('name', None))
            if not op.exists(path):
                raise FileNotFoundError("Unable to find record at '{}'".format(path))
            if path in cache:
                record = cache[path]
            else:
                record = Record.load(path=path)
                cache[path] = record
        else:
            record = Record(Record.from_yaml(record['record']))
        if isinstance(repeat, str):
            repeat = Sequence.str2repeat(repeat)
        if isinstance(speed, str):
            speed = Sequence.str2speed(speed)
        return dict(record=record, repeat=repeat, speed=speed)

    @staticmethod
    def from_yaml(records):
        # trick to not load the same record twice
        Sequence.decrypt.__defaults__[0].clear() # clear cache dict(path=<Record>)
        return list(map(Sequence.decrypt, records))

    @staticmethod
    def load(name=None, path=None):
        path = Sequence.mk_path(name=name, path=path)
        with open(path) as file:
            records = yaml.load(file)
        records = Sequence.from_yaml(records)
        sequence = Sequence(records, path=path)
        print(sequence, "loaded")
        return sequence

    @staticmethod
    def record2repeat(record):
        repeat = record.get('repeat', 1)
        if abs(repeat) == inf:
            repeat = '∞'
        elif repeat.imag != 0:
            # repeat = <times> + <seconds>j, complex here emulates Haskell Either
            repeat = "{}s".format(repeat.imag)
        return repeat

    @staticmethod
    def record2speed(record):
        speed = record.get('speed', 1)
        if speed == inf:
            speed = '∞'
        return speed

    @staticmethod
    def encrypt(record):
        record, repeat, speed = record['record'], Sequence.record2repeat(record), Sequence.record2speed(record)
        if record.path:
            if not op.exists(record.path):
                record.save()
            return dict(path=record.path, repeat=repeat, speed=speed)
        else:
            return dict(record=record.to_yaml(), repeat=repeat, speed=speed)

    def to_yaml(self):
        return list(map(Sequence.encrypt, self.records))

    def save(self, name=None, path=None):
        records = self.to_yaml()
        path = Sequence.mk_path(name=name, path=path)
        with open(path, 'w') as file:
            yaml.dump(records, file)
        self.path = path
        print(self, "saved")

    def append(self, record, repeat=1, speed=1):
        self.records.append(dict(record=record, repeat=repeat, speed=speed))

    @property
    def duration(self):
        def _duration(record):
            record, repeat, speed = record['record'], record.get('repeat', 1), record.get('speed', 1)
            if repeat.imag != 0:
                return repeat.imag
            else:
                return record.duration * repeat / speed
        return sum(map(_duration, self.records))

    @property
    def count(self):
        return len(self.records)

def pretty_dt(duration):
    hours = int(duration // 60 // 60)
    hours_str = "{}h ".format(hours) if hours else ""
    minutes = int(duration // 60 % 60)
    minutes_str = "{:d}m ".format(minutes) if minutes else ""
    seconds = duration % 60
    return "{}{}{:.2f}s".format(hours_str, minutes_str, seconds)

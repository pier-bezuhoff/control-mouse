#!/usr/bin/env python3
import time
from itertools import cycle, islice, takewhile, chain
from math import inf
from threading import Thread, Timer, Event, active_count
from pynput import mouse, keyboard
from control_mouse.settings import options, shortcuts
from control_mouse.formats import Record, Sequence

modifiers = frozenset(
        frozenset(getattr(keyboard.Key, modifier) for modifier in modifiers)
    for modifiers in options.modifiers)
all_modifiers = frozenset().union(*modifiers)
def modifiers_as(modifier):
    # ASSUMPTION: modifier in all_modifiers
    return next(m for m in modifiers if modifier in m)
def same_modifiers(a, b):
    return a == b or a in all_modifiers and b in modifiers_as(a)

the_mouse = mouse.Controller()
the_keyboard = keyboard.Controller()
manager = waiter = recorder = repeater = None


class Manager(keyboard.Listener):
    modifiers = {modifier: False for modifier in all_modifiers}
    reactions = {}
    reaction_keys = {}

    def __init__(self):
        keyboard.Listener.__init__(
            self, name='manager',
            on_press=self.on_press, on_release=self.on_release)
        self.press_handlers = {}
        self.release_handlers = {}
        global manager
        assert manager is None, "should be only one manager"
        manager = self
        self.react(shortcuts.about, self.debug)

    def debug(self):
        print('+' * 10, 'Manager.debug:')
        for shortcut, action in self.reactions.items():
            print("{}: {}".format(shortcut, action.__qualname__))
        for modifier, state in self.modifiers.items():
            if state:
                print("{}: pressed".format(modifier))
        print("running: {}".format(self.running))
        print('-' * 10)

    def on_press(self, key):
        # for on_press in self.press_handlers.values():
        #     on_press(key)
        if key in all_modifiers:
            Manager.modifiers[key] = True
        else:
            if options.keyboard_echo:
                print('[', '-'.join(tuple(
                    modifier.name for modifier in all_modifiers
                    if Manager.modifiers[modifier]) + (str(key),)), ']')
            if key in self.reaction_keys:
                for action in (
                        action for (shortcut, action) in self.reactions.items()
                        if self.pressed(key, shortcut)):
                    print("{}()".format(action.__qualname__))
                    action()

    def on_release(self, key):
        # for on_release in self.release_handlers.values():
        #     on_release(key)
        if key in all_modifiers:
            Manager.modifiers[key] = False
            if options.keyboard_echo:
                print('[-', key.name, ']')

    def on(self, modifier):
        # also check all aliases specified in settings.options.modifiers
        return self.modifiers[modifier] or any(
            self.modifiers[m] for m in modifiers_as(modifier))

    def pressed(self, key, shortcut):
        modifiers, the_key = shortcut[:-1], shortcut[-1]
        # TODO: modifiers == pressed, not <=
        return key == the_key and all(map(self.on, modifiers))

    def react(self, shortcut, callback):
        key = shortcut[-1]
        if key in self.reaction_keys:
            self.reaction_keys[key] += 1
        else:
            self.reaction_keys[key] = 1
        self.reactions[shortcut] = callback
        print('react', shortcut, callback.__qualname__)

    def unreact(self, shortcut):
        assert shortcut in self.reactions
        key = shortcut[-1]
        if self.reaction_keys[key] == 1:
            del self.reaction_keys[key]
        else:
            self.reaction_keys[key] -= 1
        del self.reactions[shortcut]
        print('unreact', shortcut)


class Managed:
    def __init__(
            self, title=None, always={}, when_paused={}, when_running={},
            press_handler=None, release_handler=None):
        "`title` should be unique if `_handler` is not None"
        self.title = title
        self.always = always
        self.when_paused = when_paused
        self.when_running = when_running
        self.press_handler = press_handler
        self.release_handler = release_handler
        # NOTE: pynput.keyboard.Listener has property 'running'
        self.running = False

    def start(self):
        assert manager
        assert manager.running
        assert not self.running
        for shortcut, action in chain(
                self.always.items(), self.when_running.items()):
            manager.react(shortcut, action)
        self.handlers_on()
        self.running = True

    def pause(self):
        assert self.running
        for shortcut in self.when_running:
            manager.unreact(shortcut)
        for shortcut, action in self.when_paused.items():
            manager.react(shortcut, action)
        self.handlers_off()
        self.running = False

    def resume(self):
        assert not self.running
        for shortcut in self.when_paused:
            manager.unreact(shortcut)
        for shortcut, action in self.when_running.items():
            manager.react(shortcut, action)
        self.handlers_on()
        self.running = True

    def stop(self):
        for shortcut in chain(
                self.always,
                self.when_running if self.running else self.when_paused):
            manager.unreact(shortcut)
        if self.running:
            self.handlers_off()

    def handlers_on(self):
        if self.press_handler:
            manager.press_handlers[self.title] = self.press_handler
        if self.release_handler:
            manager.release_handlers[self.title] = self.release_handler

    def handlers_off(self):
        if self.press_handler:
            del manager.press_handlers[self.title]
        if self.release_handler:
            del manager.release_handlers[self.title]


class Recorder(Thread, Managed):
    def __init__(self, callback=lambda record: None):
        "`Recorder.stop` call `callback(<Record>)`"
        Thread.__init__(self)
        # always = self.stripping({
        #     shortcuts.recording.stop: self.stop,
        #     shortcuts.recording.quit: self.quit})
        # when_paused = self.stripping({shortcuts.recording.resume: self.resume})
        # when_running = self.stripping({shortcuts.recording.pause: self.pause})
        always = {
            shortcuts.recording.stop: self.stop,
            shortcuts.recording.quit: self.quit}
        when_paused = {shortcuts.recording.resume: self.resume}
        when_running = {shortcuts.recording.pause: self.pause}
        Managed.__init__(
            self, title='recorder', always=always,
            when_paused=when_paused, when_running=when_running,
            press_handler=self.on_press,
            release_handler=self.on_release)
        self.callback = callback
        self.actions = []
        self.stopped = Event()
        self.time = time.monotonic()
        global recorder
        assert recorder is None
        recorder = self

    def run(self):
        print("recorder started...")
        # MAYBE: turn off mouse.Listener when pause
        with mouse.Listener(
                on_move=self.on_move,
                on_click=self.on_click,
                on_scroll=self.on_scroll) as self.mouse_listener:
            Managed.start(self)
            self.stopped.wait()
        Managed.stop(self)
        global recorder
        recorder = None

    def record_wait(self):
        current_time = time.monotonic()
        self.append(dict(action='wait', time=current_time - self.time))
        self.time = current_time

    def on_move(self, x, y):
        if self.running and options.record_motion:
            self.record_wait()
            self.append(
                dict(action='motion', x=x, y=y))

    def on_click(self, x, y, button, pressed):
        if self.running:
            self.record_wait()
            self.append(
                dict(action='mouse', pressed=pressed, x=x, y=y, button=button))

    def on_scroll(self, x, y, dx, dy):
        if self.running and options.record_scrolling:
            self.record_wait()
            self.append(
                dict(action='scroll', x=x, y=y, dx=dx, dy=dy))

    def on_press(self, key):
        if options.record_keyboard:
            self.record_wait()
            self.append(
                dict(action='key', key=key, pressed=True))

    def on_release(self, key):
        if options.record_keyboard:
            self.record_wait()
            self.append(
                dict(action='key', key=key, pressed=False))

    def append(self, d):
        self.actions.append(d)

    def pause(self):
        Managed.pause(self)
        self.delay = time.monotonic()
        print("recorder paused")

    def resume(self):
        self.time += time.monotonic() - self.delay
        Managed.resume(self)
        print("recorder resumed")

    def _stop(self):
        self.stopped.set()

    def stop(self):
        self._stop()
        self.callback(Record(actions=self.actions))
        print("recorder ended.")

    def quit(self):
        self._stop()
        print("recorder aborted.")

    def stripping(self, d):
        return {
            shortcut: (lambda: self.strip_shortcut(shortcut) or action())
            for shortcut, action in d.items()}

    def strip(self, n):
        "delete `n` last actions (not counting 'wait'-s)"
        self.actions = self.actions[:1-2*n]

    def strip_shortcut(self, shortcut):
        if options.record_keyboard and self.actions:
            key = shortcut[-1]
            last = self.actions[-1]
            # strip 'wait' and released `key`
            if (
                    last['action'] == 'key' and
                    last['key'] == key and
                    not last['pressed']):
                del self.actions[-2:]
            i = 0 # count trailing key if as in `shortcut`
            for expected, actual in zip(reversed(shortcut), self.actions[::-2]):
                if (
                        actual['action'] == 'key' and
                        actual['pressed'] and
                        (actual['key'] == expected or
                            actual['key'] in all_modifiers and
                            expected in modifiers_as(actual['key']))):
                    i += 1
                else:
                    break
            # delete max trailing `shortcut` and 'wait'-s
            if i > 0:
                del self.actions[-2*i:]


class Repeater(Thread, Managed):
    def __init__(self, sequence, on_end=lambda: None):
        Thread.__init__(self, name='repeater')
        always = {shortcuts.playing.stop: self.stop}
        when_paused = {shortcuts.playing.resume: self.resume}
        when_running = {
            shortcuts.playing.pause: self.pause,
            shortcuts.playing.no_wait: self.no_wait,
            # shortcuts.playing.skip: self.skip_action,
            # shortcuts.playing.repeat: self.repeat_record,
        }
        Managed.__init__(
            self, title='repeater', always=always,
            when_paused=when_paused, when_running=when_running)
        self.records = sequence.records
        self.on_end = on_end
        self.played = []
        self.resumed = Event()
        self.stopped = False
        global repeater
        assert repeater is None
        repeater = self

    def run(self):
        print("repeater started...")
        Managed.start(self)
        self.resumed.set()
        self.play_records()
        Managed.stop(self)
        if next(self.records, None) is None:
            print("repeater ended.")
        global repeater
        repeater = None
        self.on_end()

    def play_records(self):
        self.records = takewhile(lambda _: not self.stopped, self.records)
        for self.record in self.records:
            self.play_record(self.record)
            self.played.append(self.record)

    def play_record(self, record):
        self.actions = iter(record['record'].actions)
        repeat, speed = record.get('repeat', 1), record.get('speed', 1)
        def proceed(actions):
            for self.action in actions:
                self.perform(self.action, speed=speed)
                self.resumed.wait()
        if abs(repeat) == inf:
            self.actions = cycle(self.actions)
            proceed(takewhile(lambda _: not self.stopped, self.actions))
        elif repeat.imag != 0:
            end = repeat.imag + time.monotonic()
            proceed(takewhile(lambda _: not self.stopped and time.monotonic() < end, self.actions))
        else:
            n = int(repeat.real * record['record'].count)
            self.actions = islice(cycle(self.actions), n)
            proceed(takewhile(lambda _: not self.stopped, self.actions))

    def stop(self):
        self.stopped = True
        self.resumed.clear()
        if next(self.records, None) is not None:
            print("repeater stopped.")

    def pause(self):
        Managed.pause(self)
        self.resumed.clear()
        print("repeater paused")

    def resume(self):
        Managed.resume(self)
        self.resumed.set()
        print("repeater resumed")

    def no_wait(self):
        if self.action['action'] == 'wait':
            self.timer.cancel()

    def skip_action(self):
        next(self.actions, None)

    def skip_record(self):
        next(self.records, None)

    def repeat_record(self):
        if self.record:
            self.records = chain([self.record], self.records)

    def perform(self, action, speed=1):
        name = action['action']
        if name == 'wait' and action['time'] > 0:
            self.timer = Timer(action['time'] / speed, lambda: None)
            self.timer.start()
            self.timer.join()
        elif name == 'mouse':
            the_mouse.position = (action['x'], action['y'])
            if action['pressed']:
                the_mouse.press(action['button'])
            else:
                the_mouse.release(action['button'])
        elif name == 'motion':
            the_mouse.position = (action['x'], action['y'])
        elif name == 'scroll':
            the_mouse.position = (action['x'], action['y'])
            the_mouse.scroll(action['dx'], action['dy'])
        elif name == 'key':
            if action['pressed']:
                the_keyboard.press(action['key'])
            else:
                the_keyboard.release(action['key'])


class Waiter(Thread, Managed):
    def __init__(self):
        Thread.__init__(self, name='waiter')
        when_running = {
            shortcuts.quit: self.quit,
            shortcuts.recording.start: self.start_recording,
            shortcuts.playing.start: self.start_playing,
            shortcuts.record.open_last: self.open_last_record,
            shortcuts.sequence.open_last: self.open_last_sequence
        }
        Managed.__init__(
            self, title='waiter', when_running=when_running)
        global waiter
        assert waiter is None
        waiter = self
        self._record = self.sequence = None
        self.stopped = False
        self.jobs = []

    def run(self):
        print("waiter started...")
        Managed.start(self)
        print(active_count())
        while not self.stopped:
            if self.running:
                while self.jobs:
                    self.jobs.pop()(self)
        Managed.stop(self)
        print("waiter ended.")

    def add_job(self, job):
        if isinstance(job, str):
            job = getattr(Waiter, job)
        self.jobs.append(job)

    def quit(self):
        assert self.running
        if options.autosave:
            if self.record:
                self.record.save()
            if self.sequence:
                self.sequence.save()
        global the_mouse, the_keyboard
        if the_keyboard:
            # BUG: waiter do not stop until next press, so:
            # the_keyboard.press(keyboard.Key.esc)
            pass
        the_mouse = the_keyboard = None
        self.stopped = True

    def start_recording(self):
        Managed.pause(self)
        Recorder(callback=self.on_end_recording).start()

    def on_end_recording(self, record):
        self.record = record
        Managed.resume(self)

    def start_playing(self):
        if self.sequence:
            Managed.pause(self)
            print(active_count())
            r = Repeater(
                sequence=self.sequence,
                on_end=self.on_end_playing)
            Thread.start(r)
        else:
            print("Nothing to play!")

    def on_end_playing(self):
        Managed.resume(self)
        print(manager.running)
        print(active_count())

    def open_last_record(self):
        # TODO: in separate thread
        self.record = Record.load()
        print("last record loaded")

    def open_last_sequence(self):
        # TODO: in separate thread
        self.sequence = Sequence.load()
        print("last sequence loaded")

    @property
    def record(self):
        return self._record

    @record.setter
    def record(self, new_record):
        if options.autosave and self._record:
            self._record.save()
        self._record = new_record
        # if self.sequence is None:
        self.sequence = Sequence.single(new_record)


def main():
    waiter = Waiter()
    with Manager():
        waiter.start()
        waiter.join()


if __name__ == "__main__":
    main()

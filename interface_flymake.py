#!/usr/bin/env python3
import os.path as op
from functools import wraps
from operator import setitem
import kivy
kivy.require('1.10.0')
from kivy.app import App
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.behaviors import FocusBehavior
from kivy.properties import ObjectProperty, AliasProperty, BoundedNumericProperty, BooleanProperty, StringProperty
import control_mouse.main as cm
from control_mouse.settings import options
from control_mouse.formats import Record, Sequence


# TODO: implement editing settings.yaml via kivy...Settings (see kivy-examples)
def hook(cls, **hooks):
    """change methods of `cls`
    hooks = dict(method_name=(lambda: <action>, <post : bool>))"""
    # useless?
    for name, (action, post) in hooks.items():
        method = getattr(cls, name)
        if post:
            @wraps(method)
            def wrapped(*args, **kwargs):
                result = method(*args, **kwargs)
                action()
                return result
        else:
            @wraps(method)
            def wrapped(*args, **kwargs):
                action()
                return method(*args, **kwargs)
        setattr(cls, name, wrapped)


def hooked(self, name, post=True):
    # useless?
    if post:
        def callback():
            getattr(self, name)()
            self.hooks.get(name, lambda: None)()
    else:
        def callback():
            self.hooks.get(name, lambda: None)()
            getattr(self, name)()
    return callback


class OpenFileDialog(FocusBehavior, Popup):
    # BUG?: doesn't dismiss properly, but only if not _.bind(on_dismiss=_)
    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        selection = self.ids['filechooser'].selection
        if keycode[1] == 'enter' and selection:
            self.open_callback(selection[0])


class Row(BoxLayout):
    number = BoundedNumericProperty(0, min=0)
    rrs = ObjectProperty(force_dispatch=True) # self.property('rrs').dispatch(self) after change without assignment
    record = AliasProperty(
        lambda self: self.rrs['record'],
        lambda self, record: setitem(self.rrs, 'record', record) or self.property('rrs').dispatch(self),
        bind=['rrs'])
    name = AliasProperty(
        lambda self: self.record.name or "#{}".format(self.number),
        lambda self, name: setattr(self.record, 'name', name),
        bind=['record', 'number'])
    def set_repeat(self, repeat):
        try:
            self.rrs['repeat'] = Sequence.str2repeat(repeat)
            self.property('rrs').dispatch(self)
        except ValueError:
            # MAYBE: red higlighting + chance to fix
            print("Wrong `repeat` format: '{}'".format(repeat))
            repeat = str(Sequence.record2repeat(self.rrs))
            # FIXME: when == 1, then wrong format, wrong input doesn't change but treated as '1' (force_dispatch?)
            self.repeat = '0'
            self.repeat = repeat
    repeat = AliasProperty(
        lambda self: str(Sequence.record2repeat(self.rrs)),
        set_repeat,
        bind=['rrs'])
    def set_speed(self, speed):
        try:
            self.rrs['speed'] = Sequence.str2speed(speed)
            self.property('rrs').dispatch(self)
        except ValueError:
            print("Wrong `speed` format: '{}'".format(speed))
            speed = str(Sequence.record2speed(self.rrs))
            self.speed = '0'
            self.speed = speed
    speed = AliasProperty(
        lambda self: str(Sequence.record2speed(self.rrs)),
        set_speed,
        bind=['rrs'])


class Table(BoxLayout):
    sequence = ObjectProperty(None, allownone=True)

    def on_sequence(self, table, sequence):
        self.clear_widgets()
        if sequence:
            for i in range(sequence.count):
                row = Row(rrs=sequence.records[i], number=i)
                self.add_widget(row)

    def on_select_all_records(self, active):
        for row in self.children:
            row.ids['select'].active = active

    @property
    def selected(self):
        return [row for row in self.children if row.ids['select'].active]


class Interface(BoxLayout):
    pass


class InterfaceApp(App):
    title = "Control Mouse"
    record = ObjectProperty(allownone=True)
    sequence = ObjectProperty(allownone=True)

    def on_start(self):
        self._keyboard = Window.request_keyboard(self._keyboard_closed, self)
        self._keyboard.bind(on_key_down=self._on_key_down)
        cm.Waiter.hooks = dict(
            start_recording=self.on_start_recording,
            end_recording=self.on_end_recording,
            start_playing=self.on_start_playing,
            open_last_record=lambda: setattr(self, 'record', cm.waiter.record),
            open_last_sequence=lambda: setattr(self, 'sequence', cm.waiter.sequence),
            quit=self.stop,
        )
        cm.Recorder.hooks = dict(
            pause=self.on_pause_recording,
            resume=self.on_resume_recording,
            # quit=
        )
        cm.Repeater.hooks = dict(
            pause=self.on_pause_playing,
            resume=self.on_resume_playing,
            stop=self.on_stop_playing,
            quit=self.on_end_playing
        )
        cm.Waiter().start()

    def on_stop(self):
        cm.waiter.quit()

    def _keyboard_closed(self):
        self._keyboard.unbind(on_key_down=self._on_key_down)
        self._keyboard = None

    def _on_key_down(self, keyboard, keycode, text, modifiers):
        pass

    def on_record(self, _, record):
        if record:
            cm.waiter.record = record

    def on_sequence(self, _, sequence):
        if sequence:
            cm.waiter.sequence = sequence

    def debug(self):
        print('waiter: ', cm.waiter, ', recorder: ', cm.recorder, ', repeater: ', cm.repeater)

    def new_record(self):
        if self.record and options.autosave:
            self.save_record()
        self.record = None

    def open_record(self):
        dialog = OpenFileDialog(title="Open Record")
        dialog.size_hint = (0.9, 0.9)
        def open_callback(path):
            record = Record.load(path=path)
            dialog.dismiss()
            self.record = record
        dialog.open_callback = open_callback
        dialog.default_path = Record.directory
        def on_dismiss(_):
            dialog.clear_widgets()
        dialog.bind(on_dismiss=on_dismiss)
        dialog.open()

    def open_last_record(self):
        if op.exists(Record.autosave_path):
            self.record = Record.load()
        else:
            print("There is no autosaved record!")

    def save_record(self, name=None):
        self.record.save(name=name)
        # update links in table
        if self.sequence:
            path = self.record.path
            for row in self.root.ids['table'].children:
                if row.record.path == path:
                    row.record = self.record

    def new_sequence(self):
        if self.sequence and options.autosave:
            self.sequence.save()
        self.sequence = None

    def open_sequence(self):
        dialog = OpenFileDialog(title="Open Sequence")
        dialog.size_hint = (0.9, 0.9)
        def open_callback(path):
            sequence = Sequence.load(path=path)
            dialog.dismiss()
            self.sequence = sequence
        dialog.open_callback = open_callback
        dialog.default_path = Sequence.directory
        def on_dismiss(_):
            dialog.clear_widgets()
        dialog.bind(on_dismiss=on_dismiss)
        dialog.open()

    def open_last_sequence(self):
        if op.exists(Sequence.autosave_path):
            self.sequence = Sequence.load()
        else:
            print("There is no autosaved sequence!")

    def to_record(self, record):
        self.record = record
        self.to_tab('record_tab')


    def start_recording(self):
        self.on_start_recording()
        cm.waiter.add_job('start_recording')

    def on_start_recording(self):
        self.to_tab('record_tab')
        self.on_resume_recording()

    def resume_recording(self):
        print('resume_recording')
        self.on_resume_recording()
        cm.recorder.resume()

    def on_resume_recording(self):
        self.root.ids['listen_record'].status = 'on'

    def pause_recording(self):
        print('pause_recording')
        cm.recorder.pause()
        # self.recorder.strip(...)
        self.on_pause_recording()

    def on_pause_recording(self):
        self.root.ids['listen_record'].status = 'pause'

    def end_recording(self):
        cm.recorder.quit()
        self.on_end_recording()

    def on_end_recording(self):
        self.record = cm.waiter.record
        self.root.ids['listen_record'].status = 'off'


    def on_start_playing(self):
        # QUESTION: play sequence by default
        if self.tab.text == 'Record':
            self.on_start_playing_record()
        elif self.tab.text == 'Sequence':
            self.on_start_playing_sequence()
        else:
            self.to_tab('sequence_tab')
            self.on_start_playing_sequence()

    def on_start_playing_record(self):
        self.on_resume_playing()

    def on_start_playing_sequence(self):
        pass

    def play_record(self):
        # assumption: in record tab
        if not self.record:
            self.record = Record.load()
        cm.waiter.record = self.record
        cm.waiter.add_job('start_playing')
        self.on_start_playing_record()

    def pause_playing_record(self):
        cm.repeater.pause()
        self.on_pause_playing()

    def on_pause_playing(self):
        if self.tab.text == 'Record':
            self.root.ids['play_record'].status = 'pause'
        else:
            pass

    def resume_playing_record(self):
        self.on_resume_playing()
        cm.repeater.resume()

    def on_resume_playing(self):
        if self.tab.text == 'Record':
            self.root.ids['play_record'].status = 'on'
        else:
            pass

    def stop_playing_record(self):
        cm.repeater.stop()
        self.on_stop_playing()

    def on_stop_playing(self):
        pass

    def on_end_playing(self):
        if self.tab.text == 'Record':
            self.root.ids['play_record'].status = 'off'
        else:
            pass

    def play_sequence(self):
        # assumption: in sequence tab
        self.on_start_playing_sequence()

    def to_tab(self, id):
        self.panel.switch_to(self.root.ids[id])

    @property
    def panel(self):
        return self.root.ids['tabbed_panel']

    @property
    def tab(self):
        return self.panel.current_tab

if __name__ == '__main__':
    InterfaceApp().run()

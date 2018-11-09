#!/usr/bin/env python3
import wx
import wx.grid as grid
import os.path as op
from datetime import timedelta
from threading import Thread
from pynput import mouse, keyboard
from webbrowser import open as open_in_editor

import control_mouse.main as cm
from control_mouse.main import Waiter
from control_mouse.formats import Record, Sequence
from control_mouse.settings import settings_file, settings, options, parent_directory


class MainWindow(wx.Frame):
    def __init__(self):
        wx.Frame.__init__(self, None, size=(400, 200))
        self.record = self.sequence = None
        self.set_title()
        self.create_menu()
        self.create_player()
        self.create_editors()
        self.create_record_list()

    def set_title(self):
        sequence = " {}:".format(self.sequence.filename) if self.sequence and self.sequence.filename else ""
        record = " {}".format(self.record.filename) if self.record and self.record.filename else ""
        self.SetTitle("Control Mouse" + sequence + record)

    def create_menu(self):
        menus = {}
        shortcuts = settings.shortcuts
        menus["&Record"] = [
            (wx.ID_ANY, "&Open...", shortcuts.record.open, self.on_open),
            (wx.ID_ANY, "Open &last", shortcuts.record.open_last, self.on_open_last),
            (wx.ID_ANY, "&Save...", shortcuts.record.save, self.on_save),
            None,
            (wx.ID_EXIT, "&Quit", shortcuts.quit, self.on_quit)
        ]
        menus["&Sequence"] = [
            (wx.ID_NEW, "&New", shortcuts.sequence.new, self.on_new_sequence),
            (wx.ID_OPEN, "&Open...", shortcuts.sequence.open, self.on_open_sequence),
            (wx.ID_ANY, "Open &last", shortcuts.sequence.open_last, self.on_open_last_sequence),
            (wx.ID_SAVE, "&Save...", shortcuts.sequence.save, self.on_save_sequence)
        ]
        menus["&Playing"] = [
            (wx.ID_ANY, "&Start", shortcuts.playing.start, self.on_start),
            (wx.ID_STOP, "S&top", shortcuts.playing.stop, self.on_stop),
            (wx.ID_ANY, "&Pause", shortcuts.playing.pause, self.on_pause),
            (wx.ID_ANY, "&Resume", shortcuts.playing.resume, self.on_resume),
            (wx.ID_ANY, "&No wait", shortcuts.playing.no_wait, self.on_no_wait),
            (wx.ID_ANY, "S&kip", shortcuts.playing.skip, self.on_skip),
            (wx.ID_ANY, "R&epeat", shortcuts.playing.repeat, self.on_repeat)
        ]
        menus["Re&cording"] = [
            (wx.ID_ANY, "&Start", shortcuts.recording.start, self.on_start_recording),
            (wx.ID_ANY, "S&top", shortcuts.recording.stop, self.on_stop_recording),
            (wx.ID_ANY, "&Pause", shortcuts.recording.pause, self.on_pause_recording),
            (wx.ID_ANY, "R&esume", shortcuts.recording.resume, self.on_resume_recording)            
        ]
        menus["&Options"] = [
            (wx.ID_PREFERENCES, "Graphical &edit", shortcuts.options.edit, self.on_options_edit),
            (wx.ID_SETUP, "&Open settings.yaml", shortcuts.options.open, self.on_options_open)
        ]
        menus["&Help"] = [
            (wx.ID_HELP, "&Help", shortcuts.help, self.on_help),
            (wx.ID_ABOUT, "&About", shortcuts.about, self.on_about)
        ]
        menu_bar = wx.MenuBar()
        for name, components in menus.items():
            menu = wx.Menu()
            for component in components:
                if component is None:
                    menu.AppendSeparator()
                else:
                    id, label, description, callback = component
                    item = menu.Append(id, label, description)
                    self.Bind(wx.EVT_MENU, lambda event, callback=callback: callback(), item)
            menu_bar.Append(menu, name)
        self.SetMenuBar(menu_bar)

    def create_player(self):
        pass

    def create_editors(self):
        class PredicateValidator(wx.PyValidator):
            def __init__(self, predicate):
                wx.Validator.__init__(self)
                self.predicate = predicate
            def Clone(self):
                return self.__class__(self.predicate)
            def Validate(self, parent):
                print(parent)
                return self.predicate(parent)
        self.speed_editor = grid.GridCellTextEditor()
        def validate_speed(s):
            return True
        self.speed_editor.SetValidator(PredicateValidator(validate_speed))
        self.repeat_editor = grid.GridCellTextEditor()
        def validate_repeat(s):
            return True
        self.repeat_editor.SetValidator(PredicateValidator(validate_repeat))

    def create_record_list(self):
        self.grid = grid.Grid(self)
        headings = ("Record", "Repeat", "Speed")
        self.grid.CreateGrid(0, len(headings))
        for i, heading in enumerate(headings):
            self.grid.SetColLabelValue(i, heading)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add((0, 0), 0, 0, 0)
        sizer.Add(self.grid, 1, wx.EXPAND, 0)
        self.Layout()

    def set_record(self, record):
        self.record = record
        self.set_title()
        if self.sequence is None:
            self.set_sequence(Sequence([dict(record=self.record)]))

    def on_open(self):
        dialog = wx.FileDialog(
            self,
            message="Select a record",
            defaultDir=Record.directory,
            defaultFile=Record.autosave_filename,
            wildcard="*" + Record.extension
        )
        if dialog.ShowModal() == wx.ID_OK:
            filename = dialog.GetFilename()
            directory = dialog.GetDirectory()
            self.set_record(Record.load(op.join(directory, filename), filename=filename))

    def on_open_last(self):
        if op.exists(Record.autosave_path):
            self.set_record(Record.load())
        else:
            print("There is no last record")

    def on_save(self):
        print("on save")

    def on_quit(self):
        self.Close(True)
        cm.waiter.quit() # BUG: wait for next (any) press

    def on_new_sequence(self):
        self.set_sequence(Sequence())

    def set_sequence(self, sequence):
        self.sequence = sequence
        self.set_title()
        n_rows = self.grid.GetNumberRows()
        if n_rows > 0:
            self.grid.DeleteRows(0, n_rows)
        self.grid.AppendRows(len(sequence.records))
        for i, entry in enumerate(sequence.records, 0):
            name = getattr(entry['record'], 'filename', '#' + str(i + 1))
            if 'repeat' in entry:
                repeat = entry['repeat']
                if abs(repeat) == math.inf:
                    repeat = '∞'
                elif repeat.imag != 0:
                    repeat = str(timedelta(0, repeat.imag))
                else:
                    repeat = str(repeat.real)
            else:
                repeat = '1'
            speed = str(entry.get('speed', 1))
            self.grid.SetCellValue(i, 0, name)
            self.grid.SetReadOnly(i, 0)
            self.grid.SetCellValue(i, 1, repeat)
            self.grid.SetCellEditor(i, 1, self.repeat_editor)
            self.grid.SetCellValue(i, 2, speed)
            self.grid.SetCellEditor(i, 2, self.speed_editor)
            # TODO: bind choosing record on click
        self.grid.AutoSize()

    def on_open_sequence(self):
        dialog = wx.FileDialog(
            self,
            message="Select a sequence",
            defaultDir=Sequence.directory,
            defaultFile=Sequence.autosave_filename,
            wildcard="*" + Sequence.extension
        )
        if dialog.ShowModal() == wx.ID_OK:
            filename = dialog.GetFilename()
            directory = dialog.GetDirectory()
            self.set_sequence(Sequence.load(op.join(directory, filename), filename=filename))

    def on_open_last_sequence(self):
        if op.exists(Sequence.autosave_path):
            self.set_sequence(Sequence.load())
        else:
            print("There is no last sequence")

    def on_save_sequence(self):
        print("on save_sequence")

    def on_start(self):
        print("on start")

    def on_stop(self):
        print("on stop")

    def on_pause(self):
        print("on pause")

    def on_resume(self):
        print("on resume")

    def on_no_wait(self):
        print("on no_wait")

    def on_skip(self):
        print("on skip")

    def on_repeat(self):
        print("on repeat")

    def on_start_recording(self):
        print("on start_recording")

    def on_stop_recording(self):
        print("on stop_recording")

    def on_pause_recording(self):
        print("on pause_recording")

    def on_resume_recording(self):
        print("on resume_recording")

    def on_options_edit(self):
        print("on options_edit")

    def on_options_open(self):
        open_in_editor(settings_file)

    def on_help(self):
        with open(op.join(parent_directory, "README.md")) as file:
            dialog = wx.MessageDialog(self, file.read(), "Control Mouse Help", wx.OK)
            dialog.ShowModal()
            dialog.Destroy()

    def on_about(self):
        with open(op.join(parent_directory, "ABOUT.txt")) as file:
            dialog = wx.MessageDialog(self, file.read(), "About Control Mouse", wx.OK)
            dialog.ShowModal()
            dialog.Destroy()

def main():
    app = wx.App(False)
    frame = MainWindow()
    frame.Show()
    waiter = Waiter()
    waiter.start()
    app.MainLoop()
    waiter.join()

if __name__ == '__main__':
    main()

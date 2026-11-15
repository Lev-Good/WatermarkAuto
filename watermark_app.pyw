import hashlib
import json
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from time import monotonic
from tkinter import filedialog, messagebox, ttk

from watermark_engine import (IMAGES, POSITIONS, VIDEOS, hold_for_read, kernel,
                              output_path, render, signature)

PACKAGED = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable if PACKAGED else __file__).resolve().parent
SETTINGS = (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Watermark Auto" / "settings.json"
            if PACKAGED else APP_DIR / ".watermark-settings.json")


def find_ffmpeg():
    bundled = APP_DIR / "ffmpeg.exe"
    if bundled.is_file():
        return str(bundled)
    if PACKAGED:
        return None
    sys.path.insert(0, str(APP_DIR / ".watermark-deps"))
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return shutil.which("ffmpeg")


def watch(ffmpeg, source_dir, output_dir, logo, position, events, stop):
    observed = {}
    failed = {}
    logo_handle = None
    input_unavailable = False
    try:
        logo_handle = hold_for_read(logo)
        with logo.open("rb") as stream:
            logo_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        while not stop.is_set():
            try:
                files = sorted(source_dir.iterdir())
            except OSError as error:
                if not input_unavailable:
                    events.put(("log", f"תיקיית הקלט אינה זמינה — {error}"))
                    events.put(("status", "תיקיית הקלט אינה זמינה", "ממתין לחידוש הגישה"))
                    input_unavailable = True
                stop.wait(5)
                continue
            input_unavailable = False
            now = monotonic()
            found = set()
            ready = []
            for source in files:
                if source.suffix.lower() not in IMAGES | VIDEOS or source == logo:
                    continue
                try:
                    if not source.is_file() or source.resolve() == logo:
                        continue
                    stamp = signature(source)
                    target = output_path(source, output_dir, stamp, logo_hash, position)
                    if target.is_file() or failed.get(source) == stamp:
                        continue
                except OSError:
                    continue
                found.add(source)
                previous, first_seen = observed.get(source, (None, now))
                if stamp != previous:
                    observed[source] = (stamp, now)
                elif stamp[0] and now - first_seen >= 2:
                    ready.append((source, stamp, target))
            observed = {path: state for path, state in observed.items() if path in found}
            if not ready:
                events.put(("status", "ממתין לסיום העתקה" if found else "ממתין לקבצים",
                            f"ממתינים בתיקייה: {len(found)}"))
                stop.wait(0.75)
                continue
            locked = 0
            for index, (source, stamp, target) in enumerate(ready):
                if stop.is_set():
                    break
                try:
                    handle = hold_for_read(source)
                except OSError:
                    locked += 1
                    continue
                try:
                    if signature(source) != stamp or target.is_file():
                        continue
                    events.put(("active", source.name, len(ready) - index - 1))
                    render(ffmpeg, source, logo, position, target,
                           lambda value: events.put(("progress", value)))
                    events.put(("done", source.name, target.name))
                except (OSError, RuntimeError) as error:
                    failed[source] = stamp
                    events.put(("error", source.name, str(error)))
                finally:
                    kernel.CloseHandle(handle)
            if locked and not stop.is_set():
                events.put(("status", "ממתין לקבצים בשימוש", f"קבצים פתוחים: {locked}"))
            stop.wait(0.75)
    except OSError as error:
        events.put(("error", logo.name, str(error)))
    finally:
        if logo_handle is not None:
            kernel.CloseHandle(logo_handle)
        events.put(("stopped",))


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.closing = False
        self.successes = self.errors = 0
        self.details = []
        try:
            settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        self.paths = {key: tk.StringVar(value=settings.get(key, ""))
                      for key in ("input", "output", "logo")}
        position = settings.get("position")
        self.position = tk.StringVar(value=position if position in POSITIONS else next(iter(POSITIONS)))
        self.status = tk.StringVar(value="המעקב כבוי")
        self.current = tk.StringVar()
        self.counts = tk.StringVar(value="הושלמו 0   ·   שגיאות 0")

        root.title("סימן מים אוטומטי")
        root.minsize(660, 520)
        root.geometry("780x590")
        root.configure(background="#eef3f8")
        root.option_add("*Font", ("Segoe UI", 10))
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef3f8")
        style.configure("TLabel", background="#eef3f8", foreground="#14253b")
        style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Start.TButton", background="#1456b8", foreground="white", padding=(16, 8))
        style.map("Start.TButton", background=[("active", "#10478f"), ("disabled", "#abb7c7")])
        style.configure("Horizontal.TProgressbar", background="#246bd0", troughcolor="#dbe5f0")

        panel = ttk.Frame(root, padding=24)
        panel.pack(fill="both", expand=True)
        panel.columnconfigure(1, weight=1)
        panel.rowconfigure(10, weight=1)
        ttk.Label(panel, text="סימן מים אוטומטי", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="e", pady=(0, 17))
        self.controls = []
        for row, (key, label) in enumerate(
                (("input", "תיקיית קלט"), ("output", "תיקיית פלט"), ("logo", "קובץ סימן מים")), 1):
            ttk.Label(panel, text=label).grid(row=row, column=2, sticky="e", padx=(12, 0))
            entry = ttk.Entry(panel, textvariable=self.paths[key])
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            button = ttk.Button(panel, text="בחירה…", command=lambda item=key: self.choose(item))
            button.grid(row=row, column=0, padx=(0, 9))
            self.controls.extend(((entry, "normal"), (button, "normal")))
        ttk.Label(panel, text="מיקום סימן המים").grid(row=4, column=2, sticky="e", padx=(12, 0))
        positions = ttk.Combobox(panel, values=list(POSITIONS), textvariable=self.position,
                                 state="readonly", justify="right")
        positions.grid(row=4, column=1, sticky="e", pady=5)
        self.controls.append((positions, "readonly"))

        buttons = ttk.Frame(panel)
        buttons.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(14, 14))
        self.start_button = ttk.Button(buttons, text="התחלת מעקב", style="Start.TButton", command=self.start)
        self.start_button.pack(side="right")
        self.stop_button = ttk.Button(buttons, text="עצירת מעקב", state="disabled", command=self.request_stop)
        self.stop_button.pack(side="right", padx=8)
        ttk.Button(buttons, text="פתיחת תיקיית הפלט", command=self.open_output).pack(side="left")
        ttk.Label(panel, textvariable=self.status, style="Status.TLabel").grid(row=6, column=2, sticky="e")
        ttk.Label(panel, textvariable=self.counts).grid(row=6, column=0, columnspan=2, sticky="w")
        ttk.Label(panel, textvariable=self.current, anchor="e").grid(row=7, column=0, columnspan=3, sticky="ew")
        self.progress = ttk.Progressbar(panel)
        self.progress.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(8, 15))
        ttk.Label(panel, text="יומן פעילות").grid(row=9, column=2, sticky="e", pady=(0, 4))
        self.log = tk.Listbox(panel, borderwidth=0, highlightthickness=1, highlightbackground="#bdcbd9",
                              background="#ffffff", foreground="#14253b", exportselection=False)
        self.log.grid(row=10, column=1, columnspan=2, sticky="nsew")
        scroll = ttk.Scrollbar(panel, command=self.log.yview)
        scroll.grid(row=10, column=0, sticky="nse")
        self.log.configure(yscrollcommand=scroll.set)
        self.log.bind("<Double-1>", self.show_details)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(125, self.drain_events)

    def choose(self, key):
        if key == "logo":
            patterns = " ".join(f"*{suffix}" for suffix in sorted(IMAGES))
            path = filedialog.askopenfilename(filetypes=[("קובצי תמונה", patterns)], parent=self.root)
        else:
            path = filedialog.askdirectory(parent=self.root)
        if path:
            self.paths[key].set(path)

    def open_output(self):
        path = self.paths["output"].get().strip()
        if path and Path(path).is_dir():
            os.startfile(path)
        else:
            messagebox.showinfo("תיקיית פלט", "יש לבחור תיקיית פלט קיימת.", parent=self.root)

    def start(self):
        try:
            values = {key: entry.get().strip() for key, entry in self.paths.items()}
            if not all(values.values()):
                raise ValueError("יש לבחור תיקיית קלט, תיקיית פלט וקובץ סימן מים.")
            source, output, logo = (Path(values[key]).resolve() for key in ("input", "output", "logo"))
            if not source.is_dir() or not output.is_dir():
                raise ValueError("יש לבחור תיקיות קלט ופלט קיימות.")
            if source == output:
                raise ValueError("יש לבחור שתי תיקיות שונות.")
            if not logo.is_file() or logo.suffix.lower() not in IMAGES:
                raise ValueError("יש לבחור קובץ תמונה נתמך לסימן המים.")
            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                if PACKAGED:
                    raise ValueError("FFmpeg חסר. יש לחלץ מחדש את כל קובצי ה־ZIP לאותה תיקייה.")
                raise ValueError("FFmpeg לא נמצא. יש לפתוח את Start Watermark.cmd להתקנה.")
            position = self.position.get()
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            temporary = SETTINGS.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_text(json.dumps(dict(values, position=position), ensure_ascii=False),
                                 encoding="utf-8")
            temporary.replace(SETTINGS)
        except (OSError, ValueError) as error:
            messagebox.showerror("לא ניתן להתחיל מעקב", str(error), parent=self.root)
            return
        for widget, _ in self.controls:
            widget.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.stop.clear()
        self.status.set("ממתין לקבצים")
        self.add_log("המעקב הופעל")
        self.worker = threading.Thread(target=watch, args=(ffmpeg, source, output, logo,
                                                           position, self.events, self.stop))
        self.worker.start()

    def request_stop(self):
        self.stop.set()
        self.stop_button.configure(state="disabled")
        self.status.set("עוצר לאחר סיום העיבוד")

    def close(self):
        if self.worker is None:
            self.root.destroy()
        else:
            self.closing = True
            self.request_stop()

    def add_log(self, text, details=""):
        self.log.insert(0, f"{datetime.now():%H:%M:%S}   {text}")
        self.details.insert(0, details)
        if len(self.details) > 300:
            self.log.delete(300)
            self.details.pop()

    def show_details(self, _event):
        selection = self.log.curselection()
        if selection and self.details[selection[0]]:
            messagebox.showinfo("פרטי פעילות", self.details[selection[0]], parent=self.root)

    def set_progress(self, value):
        self.progress.stop()
        if value is None:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.configure(mode="determinate", value=value)

    def drain_events(self):
        while not self.events.empty():
            kind, *data = self.events.get_nowait()
            if kind == "status" and not self.stop.is_set():
                self.status.set(data[0])
                self.current.set(data[1])
                self.set_progress(0)
            elif kind == "active":
                if not self.stop.is_set():
                    self.status.set("מעבד קובץ")
                self.current.set(data[0])
                self.set_progress(None)
                self.add_log(f"בעיבוד — {data[0]}" + (f"  ·  בתור {data[1]}" if data[1] else ""))
            elif kind == "progress" and data[0] is not None:
                self.set_progress(data[0])
                if not self.stop.is_set():
                    self.status.set(f"מעבד קובץ · {data[0]}%")
            elif kind in ("done", "error"):
                if kind == "done":
                    self.successes += 1
                    self.set_progress(100)
                    if not self.stop.is_set():
                        self.status.set("העיבוד הושלם")
                    self.add_log(f"הושלם — {data[0]}", data[1])
                else:
                    self.errors += 1
                    self.set_progress(0)
                    if not self.stop.is_set():
                        self.status.set("שגיאה בעיבוד")
                    self.add_log(f"שגיאה — {data[0]}", data[1])
                self.counts.set(f"הושלמו {self.successes}   ·   שגיאות {self.errors}")
            elif kind == "log":
                self.add_log(data[0])
            elif kind == "stopped":
                self.worker = None
                if self.closing:
                    self.root.destroy()
                    return
                self.status.set("המעקב כבוי")
                self.current.set("")
                self.set_progress(0)
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                for widget, state in self.controls:
                    widget.configure(state=state)
                self.add_log("המעקב הופסק")
        self.root.after(125, self.drain_events)


if __name__ == "__main__":
    window = tk.Tk()
    App(window)
    window.mainloop()

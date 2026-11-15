import ctypes
import hashlib
import os
import re
import subprocess
import threading
import uuid
from collections import deque
from ctypes import wintypes
from pathlib import Path
from time import monotonic

IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
VIDEOS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".mts", ".m2ts", ".mpg", ".mpeg"}
POSITIONS = {
    "ימין למטה": ("W-w-m", "H-h-m"),
    "שמאל למטה": ("m", "H-h-m"),
    "ימין למעלה": ("W-w-m", "m"),
    "שמאל למעלה": ("m", "m"),
    "מרכז": ("(W-w)/2", "(H-h)/2"),
}
WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel.CreateFileW.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
INVALID_HANDLE = ctypes.c_void_p(-1).value


class RenderCancelled(Exception):
    pass


class RenderJob:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.cancelled = False
        self.finished = False

    def cancel(self):
        with self.lock:
            if self.finished or self.cancelled:
                return False
            self.cancelled = True
            if self.process is not None and self.process.poll() is None:
                self.process.kill()
            return True

    def start(self, args):
        with self.lock:
            self.check_cancelled()
            self.process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", creationflags=WINDOW_FLAGS)
            return self.process

    def check_cancelled(self):
        if self.cancelled:
            raise RenderCancelled

    def publish(self, temporary, target):
        with self.lock:
            self.check_cancelled()
            try:
                temporary.rename(target)
            except FileExistsError:
                # Another running window completed the same job first.
                pass
            self.finished = True

    def finish(self):
        with self.lock:
            self.process = None
            self.finished = True


def hold_for_read(path):
    # Allow FFmpeg and other readers in, while excluding writers and renames.
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle == INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def signature(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino


def output_path(source, folder, stamp, logo_hash, position):
    identity = (os.path.normcase(str(source)), stamp, logo_hash, position)
    tag = hashlib.sha256(repr(identity).encode()).hexdigest()[:14]
    suffix = ".mp4" if source.suffix.lower() in VIDEOS else source.suffix.lower()
    return folder / f"{source.stem[:70]}_watermarked_{tag}{suffix}"


def render(ffmpeg, source, logo, position, target, report, job):
    is_video = source.suffix.lower() in VIDEOS
    margin = "floor(min(W,H)*0.025)"
    x, y = (coordinate.replace("m", margin) for coordinate in POSITIONS[position])
    graph = (
        "[0:V:0]setpts=PTS-STARTPTS,split[base][ref];"
        "[1:v:0]format=rgba[logo];"
        "[logo][ref]scale=w='max(1,min(iw,floor(ref_w/4)))':"
        "h='max(1,min(ih,floor(ref_h/4)))':force_original_aspect_ratio=decrease[mark];"
        f"[base][mark]overlay=x='{x}':y='{y}':format=auto:eof_action=repeat[marked]"
    )
    if is_video:
        graph += ";[marked]pad=ceil(iw/2)*2:ceil(ih/2)*2[out]"
        options = ["-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-preset",
                   "fast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac",
                   "-b:a", "192k", "-movflags", "+faststart"]
    else:
        options = ["-map", "[marked]", "-frames:v", "1", "-update", "1"]
        if target.suffix in {".jpg", ".jpeg"}:
            options += ["-q:v", "2"]

    temporary = target.with_name(f".watermark-{uuid.uuid4().hex}{target.suffix}")
    args = [str(ffmpeg), "-hide_banner", "-nostdin", "-nostats", "-xerror", "-y",
            "-stats_period", "0.5", "-progress", "pipe:1", "-protocol_whitelist", "file",
            "-i", str(source), "-protocol_whitelist", "file", "-i", str(logo),
            "-filter_complex", graph, *options, str(temporary)]
    diagnostics = deque(maxlen=20)
    duration = 0
    first_input = True
    started = monotonic()
    try:
        with job.start(args) as process:
            for line in process.stdout:
                line = line.strip()
                if line.startswith("Input #1,"):
                    first_input = False
                if first_input and not duration:
                    match = re.match(r"Duration: (\d+):(\d+):(\d+\.\d+)", line)
                    if match:
                        hours, minutes, seconds = map(float, match.groups())
                        duration = hours * 3600 + minutes * 60 + seconds
                if line.startswith("out_time_us="):
                    value = line.partition("=")[2]
                    if is_video and duration and value.lstrip("-").isdigit():
                        report(min(99, max(0, int(int(value) / (duration * 10_000)))))
                elif line.startswith("progress=") and monotonic() - started > 1 and not duration:
                    report(None)
                elif "=" not in line or "Error" in line:
                    diagnostics.append(line)
            exit_code = process.wait()
            job.check_cancelled()
            if exit_code or not temporary.is_file() or not temporary.stat().st_size:
                raise RuntimeError("\n".join(diagnostics) or "FFmpeg לא יצר קובץ פלט.")
        job.publish(temporary, target)
    finally:
        job.finish()
        temporary.unlink(missing_ok=True)

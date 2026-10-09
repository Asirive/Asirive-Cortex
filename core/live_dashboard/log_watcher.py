"""
Log file watcher for the live dashboard.

Tails `logs/cortex.log` (or any path) and posts each new line to a
callback. Thread-safe, low-CPU, survives log rotation (re-opens the file
if it's truncated or replaced).

Why a separate thread instead of a logging.Handler:
  - We never touch the logger hierarchy, so `propagate=False` on any
    child logger can't break us.
  - The log file is the source of truth — even if the dashboard dies,
    you can `cat logs/cortex.log` and see everything.
  - Decouples the dashboard from the producer entirely.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional


class LogFileWatcher:
    """Tail a log file and call `on_line(line)` for each new line.

    Behavior:
      - Opens the file once, seeks to end (only new lines after start()).
      - Polls every `poll_interval_s` for new data; no OS-level inotify
        (RPi5's kernel is fine with it but we keep deps minimal).
      - If the file is truncated/rotated, re-opens automatically.
      - Thread-safe; multiple watchers can run in parallel.
      - Daemon thread; clean shutdown via stop() (or just kill the process).
    """

    def __init__(
        self,
        log_path: str | os.PathLike,
        on_line: Callable[[str], None],
        poll_interval_s: float = 0.1,
        start_at_end: bool = True,
    ) -> None:
        self.log_path = Path(log_path)
        self.on_line = on_line
        self.poll_interval_s = poll_interval_s
        self.start_at_end = start_at_end
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._file = None
        self._inode: Optional[int] = None
        self._lines_seen = 0
        self._errors = 0

    # --- public ---

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="log-watcher", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
        self._close_file()

    @property
    def lines_seen(self) -> int:
        return self._lines_seen

    @property
    def errors(self) -> int:
        return self._errors

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # --- internals ---

    def _open_file(self) -> None:
        """Open the log file, seek to end if start_at_end, record inode for rotation detection."""
        try:
            self._file = open(self.log_path, "r", encoding="utf-8", errors="replace")
            st = os.fstat(self._file.fileno())
            self._inode = st.st_ino
            if self.start_at_end:
                self._file.seek(0, 2)  # SEEK_END
        except FileNotFoundError:
            self._file = None
            self._inode = None
        except OSError:
            self._file = None
            self._inode = None
            self._errors += 1

    def _close_file(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
        self._file = None
        self._inode = None

    def _file_rotated(self) -> bool:
        """Detect log rotation: inode changed or file got smaller (truncate)."""
        if self._file is None or self._inode is None:
            return True
        try:
            st = os.stat(self.log_path)
            if st.st_ino != self._inode:
                return True
            pos = self._file.tell()
            if st.st_size < pos:
                return True
        except OSError:
            return True
        return False

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                # Open file if needed
                if self._file is None or self._file.closed:
                    if not self.log_path.exists():
                        self._stop.wait(self.poll_interval_s)
                        continue
                    self._open_file()
                    if self._file is None:
                        self._stop.wait(self.poll_interval_s)
                        continue

                # Detect rotation/truncation
                if self._file_rotated():
                    self._close_file()
                    continue

                line = self._file.readline()
                if line:
                    # Strip trailing newline (callback gets a clean line)
                    s = line.rstrip("\r\n")
                    try:
                        self.on_line(s)
                    except Exception:
                        # Never let a callback bug kill the watcher
                        self._errors += 1
                    self._lines_seen += 1
                else:
                    # No new data; wait a bit before polling again
                    self._stop.wait(self.poll_interval_s)
            except Exception:
                # Any unexpected error: close the file, wait, retry
                self._errors += 1
                self._close_file()
                self._stop.wait(self.poll_interval_s)

        self._close_file()

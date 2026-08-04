"""
Background job manager for the dubbing web UI.

Wraps the existing TaskRunner so the cooperative cancellation hooks already
sprinkled through core/ keep working, and records per-step wall time so the UI
can report where the run spent its time.
"""

from __future__ import annotations

import threading
import time

from core.st_utils.task_runner import TaskRunner

IDLE = {
    "name": None,
    "state": "idle",
    "progress": 0.0,
    "elapsed": None,
    "error": "",
    "steps": [],
}


class Job:
    """One pipeline run: a named sequence of steps on a single worker thread."""

    def __init__(self, name, steps):
        self.name = name
        self.labels = [label for label, _ in steps]
        self.started_at = time.time()
        self.finished_at = None
        self._step_started = [None] * len(steps)
        self._step_elapsed = [None] * len(steps)
        self._runner = TaskRunner()
        self._runner.start([(label, self._timed(index, func)) for index, (label, func) in enumerate(steps)])

    def _timed(self, index, func):
        def run():
            self._step_started[index] = time.time()
            func()
            self._step_elapsed[index] = time.time() - self._step_started[index]

        return run

    @property
    def is_active(self):
        return self._runner.is_active

    def control(self, action):
        if action == "pause":
            self._runner.pause()
        elif action == "resume":
            self._runner.resume()
        elif action == "stop":
            self._runner.stop()
        else:
            raise ValueError(f"未知操作：{action}")

    def snapshot(self):
        runner = self._runner
        if runner.is_done and self.finished_at is None:
            self.finished_at = time.time()
        now = self.finished_at or time.time()

        steps = []
        for index, label in enumerate(self.labels):
            if self._step_elapsed[index] is not None:
                status, elapsed = "done", self._step_elapsed[index]
            elif self._step_started[index] is not None:
                status = runner.state if runner.state in ("paused", "stopped", "error") else "running"
                elapsed = now - self._step_started[index]
            else:
                status, elapsed = "pending", None
            steps.append({"label": label, "status": status, "elapsed": elapsed})

        return {
            "name": self.name,
            "state": runner.state,
            "progress": runner.progress,
            "elapsed": now - self.started_at,
            "error": runner.error_msg,
            "steps": steps,
        }


_lock = threading.Lock()
_current = None


def start(name, steps):
    """Start a job, refusing to run two pipelines against the same output/ dir."""
    global _current
    with _lock:
        if _current is not None and _current.is_active:
            raise RuntimeError("已有任务在运行，先暂停或停止它。")
        _current = Job(name, steps)
        return _current.snapshot()


def snapshot():
    with _lock:
        return dict(IDLE) if _current is None else _current.snapshot()


def control(action):
    with _lock:
        if _current is None:
            raise RuntimeError("当前没有任务。")
        _current.control(action)
        return _current.snapshot()

"""Prepare candidate configurations and coordinate web and consumer reloads."""

import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

from django.conf import settings

from . import manager
from .manager import child_lock_options, directory, locked, read_state


logger = logging.getLogger(__name__)


def fingerprint(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def write_json(path, value):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            json.dump(value, file)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(candidate, lock, progress=None):
    """Run setup commands against the candidate without publishing it."""
    manage = Path(settings.BASE_DIR).parent / "manage.py"
    env = dict(os.environ, G3W_PLUGINS_CANDIDATE=str(candidate))
    for args in (("migrate", "--noinput"), ("collectstatic", "--noinput"),
                 ("sitetree_resync_apps",)):
        if progress:
            progress(args[0])
        try:
            with child_lock_options(lock) as options:
                subprocess.run([sys.executable, str(manage), *args], env=env, check=True,
                               capture_output=True, text=True, timeout=600, **options)
        except subprocess.CalledProcessError as error:
            detail = error.stderr or error.stdout
            raise RuntimeError(
                f"Preparation failed during {args[0]}: {detail}. "
                "Some database or static changes may already have been applied."
            ) from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"Preparation timed out during {args[0]}; some changes may already have been applied."
            ) from error


def available():
    return sys.platform.startswith("linux") and os.environ.get("G3WSUITE_CONSUMER") == "1"


def consumer_enabled():
    return os.environ.get("G3WSUITE_RUN_HUEY", "").lower() == "true"


def consumer_applied(target, requested_at, now):
    if not target or not isinstance(requested_at, (int, float)):
        return False
    try:
        with (directory() / "consumer-heartbeat.json").open(encoding="utf-8") as file:
            heartbeat = json.load(file)
        timestamp = heartbeat["time"]
        return (
            isinstance(timestamp, (int, float))
            and requested_at <= timestamp <= now
            and now - timestamp <= 15
            and heartbeat.get("ready") is True
            and heartbeat.get("state") == target
        )
    except FileNotFoundError:
        return False
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        logger.warning("Cannot read consumer heartbeat", exc_info=True)
        return False


def master_pid():
    if not available():
        raise RuntimeError("Process reload is available only in the G3W Docker web service")
    pid = os.getppid()
    command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    if not any(Path(os.fsdecode(arg)).name in ("gunicorn", "granian") for arg in command if arg):
        raise RuntimeError("Cannot identify the Gunicorn or Granian master process")
    return pid


def open_master():
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise RuntimeError("Automatic reload requires Linux pidfd support")
    pid = master_pid()
    fd = os.pidfd_open(pid)
    try:
        if master_pid() != pid:
            raise RuntimeError("The web master changed while starting preparation")
    except BaseException:
        os.close(fd)
        raise
    return fd


def request_reload(pidfd=None, expected_state=None):
    """Request reload only while the published configuration remains unchanged."""
    pid = master_pid() if pidfd is None else None
    root = directory()
    try:
        with locked(root, blocking=False):
            state = read_state()
            if expected_state is not None and fingerprint(state) != expected_state:
                raise RuntimeError("The plugin configuration changed after preparation; retry the reload")
            if consumer_enabled():
                try:
                    with (root / "consumer-heartbeat.json").open(encoding="utf-8") as file:
                        heartbeat = json.load(file)
                    if time.time() - heartbeat["time"] > 15:
                        raise ValueError("heartbeat expired")
                except (OSError, ValueError, KeyError, TypeError) as error:
                    raise RuntimeError(
                        "The consumer reload watcher is unavailable. Restart the consumer manually once."
                    ) from error
                write_json(root / "reload-request.json", {"state": fingerprint(state)})
            try:
                if pidfd is None:
                    os.kill(pid, signal.SIGHUP)
                else:
                    signal.pidfd_send_signal(pidfd, signal.SIGHUP)
            except OSError as error:
                raise RuntimeError(
                    f"Web reload failed: {error}. Restart the web and consumer manually."
                ) from error
            return fingerprint(state)
    except BlockingIOError as error:
        raise RuntimeError("A plugin change is still running; retry after preparation completes") from error


def watch_consumer(initial_state):
    root = directory()
    heartbeat = root / "consumer-heartbeat.json"
    request = root / "reload-request.json"
    while True:
        try:
            handler = signal.getsignal(signal.SIGHUP)
            if getattr(handler, "__name__", "") == "_handle_restart_signal":
                root.mkdir(parents=True, exist_ok=True)
                consumer = handler.__self__
                ready = (
                    not consumer._received_signal
                    and consumer.environment.is_alive(consumer.scheduler)
                    and all(consumer.environment.is_alive(worker) for _, worker in consumer.worker_threads)
                )
                write_json(heartbeat, {"time": time.time(), "state": initial_state, "ready": ready})
                if request.exists():
                    with request.open(encoding="utf-8") as file:
                        target = json.load(file)["state"]
                    if target != initial_state and target == fingerprint(read_state()):
                        os.kill(os.getpid(), signal.SIGHUP)
                        return
        except (OSError, ValueError, KeyError, TypeError):
            logger.exception("Plugin consumer reload watcher failed; retrying")
        time.sleep(2)


def start_consumer_watcher():
    if manager.configured_state is None:
        logger.error("Plugin consumer reload watcher unavailable: manager was not configured")
        return
    initial_state = fingerprint(manager.configured_state)
    threading.Thread(target=watch_consumer, args=(initial_state,), daemon=True).start()

"""Run plugin changes in background processes and report their progress."""

import contextlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

from django.conf import settings

from .manager import CATALOG, MANAGED, directory, validate_change
from .reload import available as reload_available, fingerprint, open_master, request_reload, write_json


logger = logging.getLogger(__name__)


def available():
    return os.name in ("posix", "nt")


def lock_job(root):
    root.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        from .windows_locks import Lock
        return Lock(root, "job", False)
    import fcntl

    lock = (root / ".job.lock").open("a+b")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        lock.close()
        raise
    return lock


def acquire_job(root):
    deadline = time.monotonic() + 0.5
    while True:
        try:
            return lock_job(root)
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


@contextlib.contextmanager
def locked_status(root):
    root.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        from .windows_locks import Lock
        with Lock(root, "job-status", True):
            yield
    else:
        import fcntl
        with (root / ".job-status.lock").open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def read_job(root):
    with locked_status(root):
        path = root / "job.json"
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as file:
            return json.load(file)


def write_job(root, job):
    with locked_status(root):
        write_json(root / "job.json", job)


def status():
    if not available():
        return None
    root = directory()
    try:
        lock = lock_job(root)
    except BlockingIOError:
        job = read_job(root)
        if job and job["status"] == "running":
            return job
        return {"status": "running"}
    with lock:
        job = read_job(root)
        if job is None:
            return None
        if job["status"] == "running":
            job["status"] = "failed"
            job["error"] = (
                "The operation was interrupted. The configuration, database or static files "
                "may already have changed; check the server logs and plugin state before retrying."
            )
        return job


def start(name, action, update_version=None):
    """Start one background job, passing its lock to the child process."""
    if not available():
        raise RuntimeError("Background preparation is unavailable on this platform")
    if name not in MANAGED or action not in ("enable", "disable", "update"):
        raise ValueError("Invalid plugin or action")
    if action == "update" and name not in CATALOG:
        raise ValueError("Bundled modules are updated with G3W-SUITE, not PyPI")
    if action == "update" and not update_version:
        raise ValueError("An update version is required")
    validate_change(name, action != "disable")
    root = directory()
    try:
        lock = acquire_job(root)
    except BlockingIOError as error:
        raise RuntimeError("A plugin preparation is already running") from error
    with lock:
        job = {"status": "running", "plugin": name, "action": action, "phase": "starting"}
        write_job(root, job)
        launched = False
        reload_fd = None
        try:
            env = dict(os.environ, DJANGO_SETTINGS_MODULE=settings.SETTINGS_MODULE)
            package_root = str(Path(__file__).resolve().parent.parent)
            env["PYTHONPATH"] = os.pathsep.join(
                [package_root] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
            )
            for key in ("G3W_PLUGINS_AUTO_RELOAD", "G3W_PLUGINS_RELOAD_FD",
                        "G3W_PLUGINS_RELOAD_ERROR", "G3W_PLUGINS_JOB_FD"):
                env.pop(key, None)
            if reload_available():
                env["G3W_PLUGINS_AUTO_RELOAD"] = "1"
                try:
                    reload_fd = open_master()
                    env["G3W_PLUGINS_RELOAD_FD"] = str(reload_fd)
                except (OSError, RuntimeError) as error:
                    logger.warning("Cannot prepare automatic reload: %s", error)
                    env["G3W_PLUGINS_RELOAD_ERROR"] = str(error)
            command = [sys.executable, "-m", "g3w_plugins.jobs", action, name]
            if action == "update":
                command.append(update_version)
            if os.name == "nt":
                from .windows_locks import inherited
                env["G3W_PLUGINS_JOB_HANDLE"] = str(lock.handle)
                try:
                    with inherited([lock.handle]) as options:
                        subprocess.Popen(command, env=env, cwd=Path(settings.BASE_DIR).parent,
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         start_new_session=True, **options)
                        launched = True
                finally:
                    if launched:
                        lock.detach()
            else:
                env["G3W_PLUGINS_JOB_FD"] = str(lock.fileno())
                subprocess.Popen(command, env=env, cwd=Path(settings.BASE_DIR).parent,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 start_new_session=True,
                                 pass_fds=(lock.fileno(),) + ((reload_fd,) if reload_fd is not None else ()))
        except OSError as error:
            if launched:
                raise RuntimeError(
                    f"Preparation started, but launch cleanup failed: {error}. Check its status."
                ) from error
            job.update(status="failed", error=f"Could not start preparation: {error}")
            write_job(root, job)
            raise RuntimeError(job["error"]) from error
        finally:
            if reload_fd is not None:
                os.close(reload_fd)


def retry_reload():
    root = directory()
    try:
        lock = acquire_job(root)
    except BlockingIOError as error:
        raise RuntimeError("Wait for plugin preparation to finish before reloading") from error
    with lock:
        target = request_reload()
        job = read_job(root)
        if job and job["status"] in ("succeeded", "reload_failed"):
            job.update(status="succeeded", reload="requested",
                       target=target, reload_requested_at=time.time())
            job.pop("error", None)
            write_job(root, job)


def run(action, name, update_version=None):
    job = {"status": "running", "plugin": name, "action": action, "phase": "starting"}

    def progress(phase):
        job["phase"] = phase
        write_job(directory(), job)

    try:
        import django

        django.setup()
        from .manager import change
        from .reload import prepare

        if action not in ("enable", "disable", "update") or (action == "update" and not update_version):
            raise ValueError("Invalid plugin action or update version")
        options = {}
        if action == "update":
            options = {"update_version": update_version,
                       "unmanaged_enabled": CATALOG[name] in settings.G3WADMIN_LOCAL_MORE_APPS}
        state = change(name, action in ("enable", "update"),
                       prepare=lambda candidate, lock: prepare(candidate, lock, progress=progress),
                       progress=progress, **options)
    except Exception as error:
        logger.exception("Plugin preparation failed")
        job.update(status="failed", error=f"{type(error).__name__}: {error}")
        result = 1
    else:
        job["target"] = fingerprint(state)
        if os.environ.get("G3W_PLUGINS_AUTO_RELOAD") == "1":
            progress("reload")
            try:
                error = os.environ.get("G3W_PLUGINS_RELOAD_ERROR")
                if error:
                    raise RuntimeError(error)
                request_reload(pidfd=int(os.environ["G3W_PLUGINS_RELOAD_FD"]),
                               expected_state=job["target"])
            except Exception as error:
                logger.exception("Automatic plugin reload failed")
                job.update(status="reload_failed", error=f"{type(error).__name__}: {error}")
                result = 1
            else:
                job.update(status="succeeded", reload="requested", reload_requested_at=time.time())
                result = 0
        else:
            job.update(status="succeeded", reload="manual")
            result = 0
    write_job(directory(), job)
    return result


if __name__ == "__main__":
    try:
        result = run(*sys.argv[1:])
    finally:
        if os.name == "nt" and os.environ.get("G3W_PLUGINS_JOB_HANDLE"):
            from .windows_locks import close
            close(int(os.environ["G3W_PLUGINS_JOB_HANDLE"]), release=True)
    sys.exit(result)

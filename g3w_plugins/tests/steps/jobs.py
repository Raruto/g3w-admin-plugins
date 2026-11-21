import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from behave import given, then, when

from g3w_plugins import jobs, manager


def wait_for(predicate):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for background preparation")


def cleanup_process(context, process):
    (context.root / "release").touch()
    (context.root / "stop").touch()
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)
    wait_for(lambda: not jobs.status() or jobs.status()["status"] != "running")


@given("an isolated background job directory")
def isolated_job(context):
    directory = tempfile.TemporaryDirectory()

    def cleanup_directory():
        deadline = time.monotonic() + 10
        while True:
            try:
                directory.cleanup()
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    context.add_cleanup(cleanup_directory)
    context.root = Path(directory.name)
    context.env = dict(
        os.environ, G3W_PLUGINS_DIR=str(context.root), DJANGO_SETTINGS_MODULE="jobsettings",
        PYTHONPATH=os.pathsep.join([str(context.root), *sys.path]), G3WSUITE_CONSUMER="0",
    )
    environment = patch.dict(os.environ, context.env)
    environment.start()
    context.add_cleanup(environment.stop)
    (context.root / "jobsettings.py").write_text(
        f"BASE_DIR = {str(context.root / 'base')!r}\n"
        "SECRET_KEY = 'test'\nINSTALLED_APPS = []\n"
        "ROOT_URLCONF = 'g3w_plugins.urls'\n",
        encoding="utf-8",
    )


@when("starting a job cannot launch its process")
def launch_fails(context):
    settings = SimpleNamespace(SETTINGS_MODULE="jobsettings", BASE_DIR=context.root / "base")
    with patch.object(jobs, "settings", settings), \
            patch.object(jobs, "reload_available", return_value=False), \
            patch.object(jobs.subprocess, "Popen", side_effect=OSError("test")) as launch:
        try:
            jobs.start("g3w-admin-panoramax", "disable")
        except RuntimeError as error:
            context.error = str(error)
        else:
            raise AssertionError("The launch failure was not reported")
    context.child_path = launch.call_args.kwargs["env"]["PYTHONPATH"].split(os.pathsep)


@then("the launch error is reported")
def launch_error(context):
    assert "Could not start preparation" in context.error


@then("the manager package is first on the child Python path")
def manager_first(context):
    assert context.child_path[0] == str(Path(jobs.__file__).resolve().parent.parent)


def blocking_command(context, record_parent=False):
    ready = "write_text(str(os.getppid()))" if record_parent else "touch()"
    (context.root / "manage.py").write_text(
        "import os, time\nfrom pathlib import Path\n"
        f"root = Path({str(context.root)!r})\n"
        f"(root / 'ready').{ready}\n"
        "while not (root / 'release').exists(): time.sleep(0.05)\n",
        encoding="utf-8",
    )


@given("a blocking preparation command")
def prepare_blocking_command(context):
    blocking_command(context)


@given("a blocking preparation command that records its parent")
def prepare_recording_command(context):
    blocking_command(context, record_parent=True)


def launch_worker(context):
    process = subprocess.Popen(
        [sys.executable, "-c",
         "import time\nimport django\ndjango.setup()\n"
         "from types import SimpleNamespace\nfrom unittest.mock import patch\n"
         "from django.test import RequestFactory\nfrom g3w_plugins import views\n"
         "request = RequestFactory().post('/', "
         "{'plugin': 'g3w-admin-panoramax', 'action': 'disable'})\n"
         "request.user = SimpleNamespace(is_active=True, is_superuser=True)\n"
         "with patch.object(views.messages, 'success'):\n"
         "    assert views.index(request).status_code == 302\n"
         "time.sleep(60)\n"],
        env=context.env, stdout=subprocess.DEVNULL,
    )
    context.add_cleanup(cleanup_process, context, process)
    return process


@when("a web worker starts preparation")
def start_preparation(context):
    context.worker = launch_worker(context)
    wait_for(lambda: (context.root / "ready").exists())


@then("the preparation is running in the migration phase")
def migration_running(context):
    job = jobs.status()
    assert (job["status"], job["plugin"], job["phase"]) == (
        "running", "g3w-admin-panoramax", "migrate"
    )


@then("another preparation is rejected")
def reject_concurrent(context):
    try:
        jobs.start("g3w-admin-panoramax", "disable")
    except RuntimeError as error:
        assert "already running" in str(error)
    else:
        raise AssertionError("A concurrent preparation was accepted")


@when("the web worker exits")
def worker_exits(context):
    context.worker.terminate()
    context.worker.wait(timeout=5)


@then("the preparation is still running")
def preparation_survives(context):
    assert jobs.status()["status"] == "running"


@when("the preparation command finishes")
def finish_command(context):
    (context.root / "release").touch()
    wait_for(lambda: jobs.status()["status"] != "running")


@then("preparation succeeds and the plugin is disabled")
def preparation_succeeds(context):
    assert jobs.status()["status"] == "succeeded"
    assert not manager.read_state()["plugins"]["g3w-admin-panoramax"]


@given("a preparation command that fails migration")
def failing_command(context):
    (context.root / "manage.py").write_text(
        "import sys\nprint('migration failed', file=sys.stderr)\nsys.exit(1)\n",
        encoding="utf-8",
    )


@when("a web worker starts the failing preparation")
def start_failing_preparation(context):
    context.worker = launch_worker(context)
    wait_for(lambda: jobs.status() is not None)
    wait_for(lambda: jobs.status()["status"] != "running")


@then("the migration error is reported without saving state")
def migration_failure(context):
    job = jobs.status()
    assert job["status"] == "failed"
    assert "migration failed" in job["error"]
    assert not (context.root / "state.json").exists()


@when("a previously running job is found without a worker")
def interrupted_job(context):
    context.worker.terminate()
    context.worker.wait(timeout=5)
    (context.root / "job.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")


@then("the job is reported as interrupted")
def interruption_reported(context):
    assert "interrupted" in jobs.status()["error"]


@given("Linux pidfd reload support and a blocking preparation command")
def linux_reload(context):
    if not (sys.platform.startswith("linux") and hasattr(os, "pidfd_open")
            and hasattr(signal, "pidfd_send_signal")):
        context.scenario.skip("requires Linux pidfds")
        return
    blocking_command(context)


@when("a master starts a worker that exits during preparation")
def master_starts_worker(context):
    worker = (
        "import django; django.setup()\n"
        "from g3w_plugins.jobs import start\n"
        "start('g3w-admin-panoramax', 'disable')\n"
    )
    master = (
        "import signal, subprocess, sys, time\n"
        "from pathlib import Path\n"
        f"root = Path({str(context.root)!r})\n"
        "signal.signal(signal.SIGHUP, lambda *args: (root / 'reloaded').touch())\n"
        f"subprocess.run([sys.executable, '-c', {worker!r}], check=True)\n"
        "(root / 'worker-exited').touch()\n"
        "while not (root / 'stop').exists(): time.sleep(0.05)\n"
    )
    env = dict(context.env, G3WSUITE_CONSUMER="1", G3WSUITE_RUN_HUEY="false")
    process = subprocess.Popen([sys.executable, "-c", master, "gunicorn"], env=env)
    context.add_cleanup(cleanup_process, context, process)
    wait_for(lambda: (context.root / "ready").exists())
    wait_for(lambda: (context.root / "worker-exited").exists())


@then("the master is reloaded with the prepared configuration")
def master_reloaded(context):
    wait_for(lambda: (context.root / "reloaded").exists())
    job = jobs.status()
    assert (job["status"], job["reload"]) == ("succeeded", "requested")
    assert job["target"] == jobs.fingerprint(manager.read_state())


@when("preparation succeeds but the master is unavailable")
def reload_failure(context):
    context.state = {"plugins": {"g3w-admin-panoramax": False}, "site": None}
    with patch("django.setup"), \
            patch.dict(os.environ, {"G3W_PLUGINS_AUTO_RELOAD": "1",
                                    "G3W_PLUGINS_RELOAD_ERROR": "master unavailable"}), \
            patch.object(manager, "change", return_value=context.state), \
            patch.object(jobs.logger, "exception") as log:
        context.result = jobs.run("disable", "g3w-admin-panoramax")
    log.assert_called_once_with("Automatic plugin reload failed")


@then("the reload failure and prepared target are recorded")
def reload_failure_recorded(context):
    job = jobs.read_job(context.root)
    assert context.result == 1
    assert job["status"] == "reload_failed"
    assert "master unavailable" in job["error"]
    assert job["target"] == jobs.fingerprint(context.state)


@when("an update to version 1.2 is prepared for an unmanaged enabled plugin")
def prepare_update(context):
    state = {"plugins": {"g3w-admin-panoramax": True}, "site": "site-" + "a" * 32}
    with patch("django.setup"), patch.object(jobs, "settings", SimpleNamespace(
            G3WADMIN_LOCAL_MORE_APPS=["panoramax"])), \
            patch.object(manager, "change", return_value=state) as change:
        context.result = jobs.run("update", "g3w-admin-panoramax", "1.2")
    context.change_args = change.call_args


@then("the update uses that version and succeeds")
def update_succeeds(context):
    args, kwargs = context.change_args
    assert args == ("g3w-admin-panoramax", True)
    assert kwargs["update_version"] == "1.2"
    assert kwargs["unmanaged_enabled"]
    assert context.result == 0
    assert jobs.read_job(context.root)["status"] == "succeeded"


@given("a failed reload for panoramax")
def failed_reload(context):
    jobs.write_job(context.root, {"status": "reload_failed", "plugin": "g3w-admin-panoramax",
                                  "action": "disable", "error": "watcher unavailable"})


@when("reload is retried")
def retry_reload(context):
    with patch.object(jobs, "request_reload", return_value="fingerprint"):
        jobs.retry_reload()


@then("the requested configuration is recorded without the previous error")
def retry_recorded(context):
    job = jobs.status()
    assert (job["status"], job["reload"], job["target"]) == ("succeeded", "requested", "fingerprint")
    assert "error" not in job


@when("the preparation process is killed")
def kill_preparation(context):
    os.kill(int((context.root / "ready").read_text()), signal.SIGTERM)


@then("its locks prevent another change")
def locks_are_held(context):
    assert jobs.status()["status"] == "running"
    try:
        with manager.locked(context.root, blocking=False):
            pass
    except BlockingIOError:
        pass
    else:
        raise AssertionError("The preparation lock was released")
    reject_concurrent(context)


@then("the interruption is reported without saving state")
def interrupted_without_state(context):
    assert "interrupted" in jobs.status()["error"]
    assert not (context.root / "state.json").exists()

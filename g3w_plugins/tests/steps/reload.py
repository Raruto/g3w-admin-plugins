import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from behave import given, then, when

from g3w_plugins import manager, reload


@given("an isolated reload directory")
def isolated_reload(context):
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    context.reload_root = Path(directory.name)
    environment = patch.dict(os.environ, {"G3W_PLUGINS_DIR": directory.name})
    environment.start()
    context.add_cleanup(environment.stop)


@given("POSIX reload support")
def posix_reload(context):
    if os.name == "nt":
        context.scenario.skip("requires POSIX signals")


@when("the configuration is prepared successfully")
def prepare_success(context):
    context.phases = []
    with manager.locked(context.reload_root) as lock, \
            patch.object(reload, "settings", SimpleNamespace(BASE_DIR=context.reload_root / "base")), \
            patch.object(reload.subprocess, "run"):
        reload.prepare(context.reload_root / ".state-candidate", lock, progress=context.phases.append)


@then("migration, static collection and menu synchronization are reported in order")
def preparation_phases(context):
    assert context.phases == ["migrate", "collectstatic", "sitetree_resync_apps"]


@when("migration fails during preparation")
def prepare_failure(context):
    failure = subprocess.CalledProcessError(1, "migrate", stderr="bad migration")
    with manager.locked(context.reload_root) as lock, \
            patch.object(reload, "settings", SimpleNamespace(BASE_DIR=context.reload_root / "base")), \
            patch.object(reload.subprocess, "run", side_effect=failure):
        try:
            reload.prepare(context.reload_root / ".state-candidate", lock)
        except RuntimeError as error:
            context.reload_error = str(error)
        else:
            raise AssertionError("The failed migration was accepted")


@then("the error warns that changes may already have been applied")
def partial_failure(context):
    assert "bad migration" in context.reload_error
    assert "already have been applied" in context.reload_error


@when("reload is requested with an unavailable or stale consumer")
def unavailable_consumer(context):
    heartbeat = context.reload_root / "consumer-heartbeat.json"
    with patch.dict(os.environ, {"G3WSUITE_RUN_HUEY": "true"}), \
            patch.object(reload, "master_pid", return_value=123), \
            patch.object(reload.os, "kill") as kill:
        for value in (None, time.time() - 30):
            if value is not None:
                heartbeat.write_text(json.dumps({"time": value}), encoding="utf-8")
            try:
                reload.request_reload()
            except RuntimeError as error:
                assert "watcher is unavailable" in str(error)
            else:
                raise AssertionError("Reload accepted an unavailable consumer")
        context.kill_calls = kill.call_count


@then("no web reload signal is sent")
def no_reload_signal(context):
    assert context.kill_calls == 0


@when("the consumer heartbeat becomes current")
def current_consumer(context):
    (context.reload_root / "consumer-heartbeat.json").write_text(
        json.dumps({"time": time.time()}), encoding="utf-8"
    )
    with patch.dict(os.environ, {"G3WSUITE_RUN_HUEY": "true"}), \
            patch.object(reload, "master_pid", return_value=123), \
            patch.object(reload.os, "kill") as kill:
        reload.request_reload()
    context.kill_args = kill.call_args


@then("reload is requested for the current configuration")
def current_reload_requested(context):
    request = json.loads((context.reload_root / "reload-request.json").read_text())
    assert request["state"] == reload.fingerprint({"plugins": {}, "site": None})
    assert context.kill_args.args == (123, reload.signal.SIGHUP)


@when("reload is requested with the consumer disabled")
def reload_without_consumer(context):
    with patch.dict(os.environ, {"G3WSUITE_RUN_HUEY": "false"}), \
            patch.object(reload, "master_pid", return_value=123), \
            patch.object(reload.os, "kill") as kill:
        reload.request_reload()
    context.kill_args = kill.call_args


@then("the web process is signalled without a consumer request")
def web_only(context):
    assert not (context.reload_root / "reload-request.json").exists()
    assert context.kill_args.args == (123, reload.signal.SIGHUP)


@when("consumer heartbeats are checked against the requested configuration")
def check_heartbeats(context):
    target = "expected"
    heartbeat = context.reload_root / "consumer-heartbeat.json"
    assert not reload.consumer_applied(target, 100, 110)
    context.heartbeat_results = []
    for data in (
        {"state": target, "ready": True, "time": 105},
        {"state": "old", "ready": True, "time": 105},
        {"state": target, "ready": False, "time": 105},
        {"state": target, "ready": True, "time": 99},
        {"state": target, "ready": True, "time": 111},
        {"state": target, "ready": True, "time": 90},
        {"state": target, "time": 105},
    ):
        heartbeat.write_text(json.dumps(data), encoding="utf-8")
        context.heartbeat_results.append(reload.consumer_applied(target, 100, 110))


@then("only the fresh, ready, matching heartbeat is accepted")
def valid_heartbeat(context):
    assert context.heartbeat_results == [True, False, False, False, False, False, False]


@then("invalid heartbeat data is logged and rejected")
def invalid_heartbeat(context):
    (context.reload_root / "consumer-heartbeat.json").write_text("{", encoding="utf-8")
    with patch.object(reload.logger, "warning") as warning:
        assert not reload.consumer_applied("expected", 100, 110)
    warning.assert_called_once()


@when("reload is requested while a plugin change holds the lock")
def active_change(context):
    with manager.locked(context.reload_root), patch.object(reload, "master_pid", return_value=123), \
            patch.object(reload.os, "kill") as kill:
        try:
            reload.request_reload()
        except RuntimeError as error:
            context.reload_error = str(error)
        else:
            raise AssertionError("Reload was accepted during a plugin change")
    context.kill_calls = kill.call_count


@then("the active change is reported and no signal is sent")
def change_reported(context):
    assert "plugin change is still running" in context.reload_error
    assert context.kill_calls == 0


@when("reload is requested for an outdated configuration")
def outdated_reload(context):
    with patch.object(reload, "master_pid", return_value=123), \
            patch.object(reload.os, "kill") as kill:
        try:
            reload.request_reload(expected_state="outdated")
        except RuntimeError as error:
            context.reload_error = str(error)
        else:
            raise AssertionError("Reload accepted an outdated configuration")
    context.kill_calls = kill.call_count


@then("the configuration change is reported and no signal is sent")
def configuration_change_reported(context):
    assert "configuration changed" in context.reload_error
    assert context.kill_calls == 0


class Consumer:
    _received_signal = False
    scheduler = object()
    worker_threads = [(None, object())]
    environment = SimpleNamespace(is_alive=lambda worker: True)

    def _handle_restart_signal(self, *args):
        pass


@when("a ready consumer observes a request for the new configuration")
def consumer_request(context):
    context.old_state = reload.fingerprint({"plugins": {}, "site": None})
    state = {"plugins": {"g3w-admin-panoramax": False}, "site": None}
    (context.reload_root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (context.reload_root / "reload-request.json").write_text(
        json.dumps({"state": reload.fingerprint(state)}), encoding="utf-8"
    )
    with patch.object(reload.signal, "getsignal", return_value=Consumer()._handle_restart_signal), \
            patch.object(reload.os, "kill") as kill:
        reload.watch_consumer(context.old_state)
    context.kill_args = kill.call_args


@then("it reports its current state and signals itself to reload")
def consumer_reload_requested(context):
    assert context.kill_args.args == (os.getpid(), reload.signal.SIGHUP)
    heartbeat = json.loads((context.reload_root / "consumer-heartbeat.json").read_text())
    assert heartbeat["state"] == context.old_state
    assert heartbeat["ready"]


@when("a consumer worker has stopped")
def stopped_worker(context):
    consumer = Consumer()
    consumer.environment = SimpleNamespace(is_alive=lambda worker: worker is consumer.scheduler)
    with patch.object(reload.signal, "getsignal", return_value=consumer._handle_restart_signal), \
            patch.object(reload.time, "sleep", side_effect=InterruptedError):
        try:
            reload.watch_consumer("current")
        except InterruptedError:
            pass
        else:
            raise AssertionError("Consumer watcher did not stop")


@then("the consumer heartbeat is not ready")
def consumer_not_ready(context):
    heartbeat = json.loads((context.reload_root / "consumer-heartbeat.json").read_text())
    assert not heartbeat["ready"]


@when("a running consumer task delays a configuration reload")
def running_consumer(context):
    script = context.reload_root / "consumer.py"
    script.write_text(
        "from pathlib import Path\n"
        "import multiprocessing, time\n"
        "from huey import MemoryHuey\n"
        "from huey.consumer import Consumer\n"
        "from g3w_plugins import manager, reload\n"
        "multiprocessing.set_start_method('fork')\n"
        "root = manager.directory()\n"
        "manager.configured_state = manager.read_state()\n"
        "huey = MemoryHuey(immediate=False)\n"
        "@huey.task()\n"
        "def hold():\n"
        "    (root / 'entered').touch()\n"
        "    while not (root / 'release').exists(): time.sleep(0.05)\n"
        "if not (root / 'started').exists():\n"
        "    (root / 'started').touch()\n"
        "    hold()\n"
        "reload.start_consumer_watcher()\n"
        "Consumer(huey, workers=1, worker_type='process', initial_delay=0.01).run()\n",
        encoding="utf-8",
    )
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    process = subprocess.Popen([sys.executable, str(script)], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    context.consumer_process = process

    def stop_consumer():
        (context.reload_root / "release").touch()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        process.stderr.close()

    context.add_cleanup(stop_consumer)
    old = reload.fingerprint(manager.read_state())
    wait_for_consumer(context, lambda: (context.reload_root / "entered").exists()
                      and reload.consumer_applied(old, 0, time.time()))
    state = {"plugins": {"g3w-admin-panoramax": False}, "site": None}
    context.target = reload.fingerprint(state)
    reload.write_json(context.reload_root / "state.json", state)
    context.requested_at = time.time()
    reload.write_json(context.reload_root / "reload-request.json", {"state": context.target})


def wait_for_consumer(context, predicate):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if context.consumer_process.poll() is not None:
            raise AssertionError(f"consumer exited unexpectedly: {context.consumer_process.stderr.read()}")
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("consumer did not reach expected state")


@then("the consumer confirms only after the task finishes")
def consumer_confirms_after_task(context):
    time.sleep(3)
    assert context.consumer_process.poll() is None
    assert not reload.consumer_applied(context.target, context.requested_at, time.time())
    (context.reload_root / "release").touch()
    wait_for_consumer(context, lambda: reload.consumer_applied(
        context.target, context.requested_at, time.time()
    ))

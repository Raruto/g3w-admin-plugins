import contextlib
import importlib.util
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

from g3w_plugins import manager


@given("an isolated plugin configuration")
def isolated_manager(context):
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    context.manager_root = Path(directory.name)
    environment = patch.dict(os.environ, {"G3W_PLUGINS_DIR": directory.name})
    environment.start()
    context.add_cleanup(environment.stop)
    old_path = sys.path[:]
    context.add_cleanup(lambda: sys.path.__setitem__(slice(None), old_path))


def install(command, **kwargs):
    site = Path(command[command.index("--target") + 1])
    site.mkdir()
    for argument in command:
        package = argument.split("==", 1)[0]
        if package in manager.CATALOG:
            module = site / manager.CATALOG[package]
            module.mkdir()
            (module / "__init__.py").write_text("", encoding="utf-8")


def rejected(function, exception, message):
    try:
        function()
    except exception as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError(f"Expected {exception.__name__}: {message}")


@when("the manager runs in Docker without a configured directory")
def docker_directory(context):
    context.docker_root = context.manager_root / ".g3w_plugins"
    with patch.dict(os.environ, {}, clear=True), patch.object(manager, "in_docker", return_value=True), \
            patch.object(manager, "DOCKER_PLUGIN_DIR", context.docker_root):
        context.directory = manager.directory()
        context.directory_env = os.environ["G3W_PLUGINS_DIR"]


@then("the Docker plugin directory is used")
def docker_default(context):
    assert context.directory == context.docker_root.resolve()
    assert context.directory_env == str(context.docker_root.resolve())


@when("the manager runs outside Docker without a configured directory")
def host_directory(context):
    with patch.dict(os.environ, {"G3W_PLUGINS_DIR": ""}), \
            patch.object(manager, "in_docker", return_value=False), \
            patch.object(Path, "home", return_value=context.manager_root):
        context.directory = manager.directory()
        context.directory_env = os.environ["G3W_PLUGINS_DIR"]
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(Path(manager.__file__).resolve().parent.parent), env.get("PYTHONPATH", "")]
        )
        child = subprocess.run(
            [sys.executable, "-c", "from g3w_plugins.manager import directory; print(directory())"],
            cwd=context.manager_root, env=env, text=True, capture_output=True, check=True,
        )
        context.child_directory = Path(child.stdout.strip())


@then("the plugin directory in the service user's home is used")
def home_default(context):
    expected = (context.manager_root / ".g3w_plugins").resolve()
    assert context.directory == expected
    assert context.directory_env == str(expected)
    assert context.child_directory == expected


@when('the manager uses a configured directory in "{environment}"')
def configured_directory(context, environment):
    context.explicit_directory = context.manager_root / "custom"
    with patch.dict(os.environ, {"G3W_PLUGINS_DIR": str(context.explicit_directory)}), \
            patch.object(manager, "in_docker", return_value=environment == "Docker"):
        context.directory = manager.directory()
        context.directory_env = os.environ["G3W_PLUGINS_DIR"]


@then("the configured plugin directory is used")
def explicit_default(context):
    assert context.directory == context.explicit_directory.resolve()
    assert context.directory_env == str(context.explicit_directory)


@when("the manager configures an app list containing itself")
def configure_existing(context):
    context.apps = ["editing", "g3w_plugins"]
    manager.configure(context.apps)


@then("the manager appears only once")
def one_manager(context):
    assert context.apps == ["editing", "g3w_plugins"]


@when("panoramax is enabled and then disabled")
def enable_disable(context):
    with patch.object(manager.subprocess, "run", side_effect=install):
        manager.change("g3w-admin-panoramax", True)
    assert manager.read_state()["plugins"]["g3w-admin-panoramax"]
    context.enabled_apps = ["editing", "portal"]
    manager.configure(context.enabled_apps)
    manager.change("g3w-admin-panoramax", False)
    context.disabled_state = manager.read_state()
    context.disabled_apps = ["editing", "portal", "panoramax"]
    manager.configure(context.disabled_apps)


@then("unmanaged applications remain configured")
def unmanaged_remain(context):
    assert context.enabled_apps == ["editing", "portal", "panoramax", "g3w_plugins"]
    assert context.disabled_state["site"] is None
    assert context.disabled_apps == ["editing", "portal", "g3w_plugins"]


@when('panoramax is "{condition}" in its managed installation')
def managed_plugin_availability(context, condition):
    site = context.manager_root / ("site-" + "d" * 32)
    site.mkdir()
    (context.manager_root / "state.json").write_text(json.dumps({
        "plugins": {"g3w-admin-panoramax": True}, "site": site.name,
    }), encoding="utf-8")
    other = context.manager_root / "other"
    other.mkdir()
    paths = [other] if condition == "missing" else (
        [site] if condition == "namespace only in managed installation" else [other, site]
    )
    for path in paths:
        module = path / "panoramax"
        module.mkdir()
        if not condition.startswith("namespace") or (
            condition == "namespace with regular global app" and path == other
        ):
            (module / "__init__.py").write_text("", encoding="utf-8")
    sys.path.insert(0, str(other))
    if condition == "missing" or condition.startswith("namespace"):
        modules = contextlib.nullcontext()
    else:
        selected = site if condition == "loaded from its managed installation" else other
        spec = importlib.util.spec_from_file_location("panoramax", selected / "panoramax" / "__init__.py")
        modules = patch.dict(sys.modules, {"panoramax": importlib.util.module_from_spec(spec)})
    context.availability_error = None
    context.availability_apps = ["editing"]
    with modules:
        try:
            manager.configure(context.availability_apps)
        except RuntimeError as error:
            context.availability_error = str(error)


@then("configuration rejects the incompatible plugin installation")
def reject_incompatible_plugin(context):
    assert context.availability_error and "panoramax" in context.availability_error
    assert context.availability_apps == ["editing"]


@then("the managed plugin remains configured")
def accept_managed_plugin(context):
    assert context.availability_error is None, context.availability_error
    assert "panoramax" in context.availability_apps


@when("preparation of panoramax fails before publication")
def failed_preparation(context):
    context.before = manager.read_state()

    def fail(candidate, lock):
        assert manager.read_state() == context.before
        assert manager.read_state(candidate)["plugins"]["g3w-admin-panoramax"]
        raise RuntimeError("migration failed")

    with patch.object(manager.subprocess, "run", side_effect=install):
        rejected(lambda: manager.change("g3w-admin-panoramax", True, prepare=fail),
                 RuntimeError, "migration failed")


@then("the previous state remains and the candidate is removed")
def state_not_published(context):
    assert manager.read_state() == context.before
    assert not list(context.manager_root.glob(".state-*"))


@given("panoramax and portal are installed")
def installed_plugins(context):
    site = "site-" + "a" * 32
    (context.manager_root / site).mkdir()
    context.before = {"plugins": {"g3w-admin-panoramax": True, "g3w-admin-portal": True}, "site": site}
    (context.manager_root / "state.json").write_text(json.dumps(context.before), encoding="utf-8")
    context.installed = [
        SimpleNamespace(metadata={"Name": "g3w-admin-panoramax"}, version="1.0"),
        SimpleNamespace(metadata={"Name": "g3w-admin-portal"}, version="2.0"),
    ]


def distributions(context, **kwargs):
    return context.installed if kwargs.get("path") else []


@when("panoramax is updated to version 1.1")
def prepare_update(context):
    context.commands = []

    def fake_install(command, **kwargs):
        context.commands.append(command)
        install(command, **kwargs)

    def fail(candidate, lock):
        raise RuntimeError("migration failed")

    with patch.object(manager.importlib.metadata, "distributions",
                      side_effect=lambda **kwargs: distributions(context, **kwargs)), \
            patch.object(manager.subprocess, "run", side_effect=fake_install):
        rejected(lambda: manager.change("g3w-admin-panoramax", True, update_version="1.1", prepare=fail),
                 RuntimeError, "migration failed")
        context.failed_state = manager.read_state()
        rejected(lambda: manager.change("g3w-admin-panoramax", True, update_version="1.0"),
                 ValueError, "not newer")
        rejected(lambda: manager.change("g3w-admin-panoramax", True, update_version="2.0rc1"),
                 ValueError, "stable")
        context.updated = manager.change("g3w-admin-panoramax", True, update_version="1.1")


@then("portal remains pinned and failed preparation preserves the state")
def pinned_and_preserved(context):
    assert context.failed_state == context.before
    assert "g3w-admin-panoramax==1.1" in context.commands[0]
    assert "g3w-admin-portal==2.0" in context.commands[0]


@then("non-newer and prerelease versions are rejected")
def invalid_upgrade_rejected(context):
    assert len(context.commands) == 2


@then("successful preparation publishes a new site")
def new_site(context):
    assert context.updated["site"] != context.before["site"]
    assert manager.read_state() == context.updated


@when("an update is requested for disabled panoramax")
def update_disabled(context):
    with patch.object(manager.subprocess, "run") as pip:
        rejected(lambda: manager.change("g3w-admin-panoramax", True, update_version="1.1"),
                 ValueError, "Only enabled")
    context.pip_calls = pip.call_count


@then("the update is rejected before installation")
def no_install(context):
    assert context.pip_calls == 0


@given("an external portal installation")
def external_portal(context):
    context.site = "site-" + "c" * 32
    module = context.manager_root / context.site / "portal"
    module.mkdir(parents=True)
    (module / "__init__.py").write_text("", encoding="utf-8")
    (context.manager_root / "state.json").write_text(json.dumps({
        "plugins": {"g3w-admin-portal": True}, "site": context.site,
    }), encoding="utf-8")


@when("filemanager is disabled and enabled")
def toggle_bundled(context):
    with patch.object(manager.importlib.util, "find_spec", return_value=object()), \
            patch.object(manager.subprocess, "run") as pip:
        manager.change("filemanager", False)
        context.disabled_site = manager.read_state()["site"]
        context.disabled_apps = ["editing", "filemanager", "qplotly"]
        manager.configure(context.disabled_apps)
        manager.change("filemanager", True)
        context.enabled_apps = ["editing", "filemanager", "qplotly"]
        manager.configure(context.enabled_apps)
    context.pip_calls = pip.call_count


@then("the external installation remains unchanged and pip is not called")
def bundled_no_install(context):
    assert context.disabled_site == context.site
    assert "filemanager" not in context.disabled_apps
    assert context.enabled_apps[:3] == ["editing", "filemanager", "qplotly"]
    assert context.pip_calls == 0


@then("updating filemanager as a package is rejected")
def bundled_update_rejected(context):
    rejected(lambda: manager.change("filemanager", True, update_version="2.0"), ValueError, "Bundled modules")


@when("qplotly is available but qtimeseries is missing")
def bundled_availability(context):
    with patch.object(manager.importlib.util, "find_spec", return_value=object()):
        manager.change("qplotly", True)
    with patch.object(manager.importlib.util, "find_spec", return_value=None):
        rejected(lambda: manager.change("qtimeseries", True), RuntimeError, "not available")


@then("qplotly is enabled and the missing module is rejected")
def bundled_state(context):
    assert manager.read_state() == {"plugins": {"qplotly": True}, "site": None}


@when("editing is disabled with qes installed")
def disable_editing(context):
    from django.apps import apps
    with patch.object(apps, "ready", True), patch.object(apps, "is_installed", return_value=True), \
            patch.object(manager.subprocess, "run") as prepare:
        rejected(lambda: manager.change("editing", False), RuntimeError, "qes requires editing")
    context.pip_calls = prepare.call_count


@then("the dependency error is reported without changing state")
def editing_rejected(context):
    assert context.pip_calls == 0
    assert manager.read_state() == {"plugins": {}, "site": None}


@when("disabling filemanager fails during preparation")
def bundled_preparation_fails(context):
    context.before = {"plugins": {"filemanager": True}, "site": None}
    (context.manager_root / "state.json").write_text(json.dumps(context.before), encoding="utf-8")

    def fail(candidate, lock):
        assert not manager.read_state(candidate)["plugins"]["filemanager"]
        raise RuntimeError("migration failed")

    rejected(lambda: manager.change("filemanager", False, prepare=fail), RuntimeError, "migration failed")


@then("the bundled configuration remains unchanged")
def bundled_preserved(context):
    assert manager.read_state() == context.before


@when("panoramax is installed alongside filemanager")
def install_external(context):
    (context.manager_root / "state.json").write_text(json.dumps({
        "plugins": {"filemanager": True}, "site": None,
    }), encoding="utf-8")
    with patch.object(manager.subprocess, "run", side_effect=install) as pip:
        manager.change("g3w-admin-panoramax", True)
    context.pip_command = pip.call_args.args[0]


@then("pip is not asked to install filemanager")
def bundled_excluded(context):
    assert "filemanager" not in context.pip_command


@when("untrusted plugin names and an invalid site path are supplied")
def untrusted_input(context):
    with patch.object(manager.subprocess, "run") as pip:
        for name in ("../untrusted", "g3w-admin-portal[evil]", "git+https://evil.invalid/repo"):
            rejected(lambda: manager.change(name, True), ValueError, "")
    context.pip_calls = pip.call_count
    (context.manager_root / "state.json").write_text(json.dumps({
        "plugins": {"g3w-admin-panoramax": True}, "site": "../outside",
    }), encoding="utf-8")
    rejected(manager.read_state, ValueError, "")


@then("they are rejected without installing packages")
def untrusted_rejected(context):
    assert context.pip_calls == 0


@when("requested or installed versions contain injected text")
def injected_versions(context):
    with patch.object(manager.importlib.metadata, "distributions",
                      side_effect=lambda **kwargs: distributions(context, **kwargs)), \
            patch.object(manager.subprocess, "run") as pip:
        rejected(lambda: manager.change("g3w-admin-panoramax", True, update_version="2.0; evil"),
                 ValueError, "Invalid update version")
        context.installed[1].version = "1.0; evil"
        rejected(lambda: manager.change("g3w-admin-panoramax", True, update_version="2.0"),
                 RuntimeError, "Invalid installed plugin version")
    context.pip_calls = pip.call_count


@then("both versions are rejected before installation")
def injection_rejected(context):
    assert context.pip_calls == 0


@when("a preparation parent is terminated while its command is running")
def kill_parent(context):
    root = context.manager_root
    (root / "manage.py").write_text(
        "from pathlib import Path\nimport time\n"
        "Path('ready').touch()\n"
        "while not Path('release').exists(): time.sleep(0.05)\n",
        encoding="utf-8",
    )
    script = (
        "from pathlib import Path\nfrom django.conf import settings\n"
        f"settings.configure(BASE_DIR=Path({str(root)!r}) / 'base')\n"
        "from g3w_plugins.manager import change\nfrom g3w_plugins.reload import prepare\n"
        "change('g3w-admin-panoramax', False, prepare=prepare)\n"
    )
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    process = subprocess.Popen([sys.executable, "-c", script], cwd=root, env=env)
    context.parent = process
    context.waiter = None

    def cleanup():
        (root / "release").touch()
        for child in (context.parent, context.waiter):
            if child is not None and child.poll() is None:
                child.terminate()
                child.wait(timeout=5)

    context.add_cleanup(cleanup)
    deadline = time.monotonic() + 10
    while not (root / "ready").exists() and time.monotonic() < deadline:
        assert process.poll() is None, "parent exited before preparation"
        time.sleep(0.05)
    assert (root / "ready").exists(), "preparation did not start"
    process.terminate()
    process.wait(timeout=5)


@then("the lock is held until the command exits and no state is published")
def lock_inherited(context):
    root = context.manager_root

    def acquire_lock():
        with manager.locked(root, blocking=False):
            pass

    rejected(acquire_lock, BlockingIOError, "")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    context.waiter = subprocess.Popen(
        [sys.executable, "-c", "from pathlib import Path\nfrom g3w_plugins.manager import locked\n"
         f"with locked(Path({str(root)!r})):\n    Path('waiter-ready').touch()\n"],
        cwd=root, env=env,
    )
    time.sleep(0.3)
    assert not (root / "waiter-ready").exists()
    (root / "release").touch()
    assert context.waiter.wait(timeout=10) == 0
    assert (root / "waiter-ready").exists()
    deadline = time.monotonic() + 10
    while True:
        try:
            with manager.locked(root, blocking=False):
                break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise AssertionError("preparation did not release its lock")
            time.sleep(0.05)
    assert not (root / "state.json").exists()

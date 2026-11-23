import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from behave import given, then, when


@given("a disposable G3W Docker test container")
def disposable_container(context):
    if os.environ.get("G3W_PLUGINS_TEST_CONTAINER") != "1" or not Path("/.dockerenv").exists():
        context.scenario.skip("requires a disposable G3W Docker test container")
        return
    original_path = sys.path[:]
    context.add_cleanup(lambda: sys.path.__setitem__(slice(None), original_path))
    sys.path.insert(0, "/code/g3w-admin")


def docker_settings(environment, manager=True):
    import django.conf
    from g3w_plugins.bootstrap import SettingsLoader

    settings = SimpleNamespace(BASE_DIR="/code/g3w-admin", TEMPLATES=[{"DIRS": []}], STATICFILES_DIRS=[])
    source = Path("/tmp/docker-settings.py").read_text(encoding="utf-8")
    result = {"__name__": "<run_path>", "__file__": "/tmp/docker-settings.py"}
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / "local_settings.py"
        path.write_text(source, encoding="utf-8")
        code = (
            SettingsLoader("base.settings.local_settings", str(path)).get_code("base.settings.local_settings")
            if manager else compile(source, str(path), "exec")
        )
        with patch.object(django.conf, "settings", settings), patch.dict(os.environ, environment, clear=True):
            exec(code, result)
            return result, dict(os.environ)


@when("the Docker settings are loaded with the default manager configuration")
def default_docker_settings(context):
    context.docker_settings, context.docker_env = docker_settings({})


@then("the manager is enabled and the original portal configuration is retained")
def default_manager_enabled(context):
    assert context.docker_env["G3W_PLUGINS_DIR"] == "/shared-volume/.g3w_plugins"
    assert "g3w_plugins" in context.docker_settings["G3WADMIN_LOCAL_MORE_APPS"]
    assert "portal" in context.docker_settings["G3WADMIN_LOCAL_MORE_APPS"]
    assert "PORTAL_NAVBAR_TOP" in context.docker_settings


@when("the Docker settings are loaded with an enabled portal")
def enabled_portal(context):
    with tempfile.TemporaryDirectory() as root:
        site = Path(root) / ("site-" + "b" * 32)
        module = site / "portal"
        module.mkdir(parents=True)
        (module / "__init__.py").write_text("", encoding="utf-8")
        (Path(root) / "state.json").write_text(json.dumps({
            "plugins": {"g3w-admin-portal": True}, "site": site.name,
        }), encoding="utf-8")
        context.docker_settings, _ = docker_settings({"G3W_PLUGINS_DIR": root})


@then("portal and its settings remain configured")
def portal_enabled(context):
    assert "portal" in context.docker_settings["G3WADMIN_LOCAL_MORE_APPS"]
    assert "PORTAL_NAVBAR_TOP" in context.docker_settings


@when("the published Docker settings are loaded without the manager")
def manager_absent(context):
    context.docker_settings, context.docker_env = docker_settings({}, manager=False)


@then("portal remains configured without plugin manager state")
def original_settings(context):
    assert "G3W_PLUGINS_DIR" not in context.docker_env
    assert "g3w_plugins" not in context.docker_settings["G3WADMIN_LOCAL_MORE_APPS"]
    assert "portal" in context.docker_settings["G3WADMIN_LOCAL_MORE_APPS"]


@when("the manager disables portal in the Docker settings")
def disabled_portal(context):
    with tempfile.TemporaryDirectory() as root:
        (Path(root) / "state.json").write_text(json.dumps({
            "plugins": {"g3w-admin-portal": False}, "site": None,
        }), encoding="utf-8")
        context.docker_settings, _ = docker_settings({"G3W_PLUGINS_DIR": root})


@then("the manager remains while portal and its settings are omitted")
def disabled_portal_apps(context):
    apps = context.docker_settings["G3WADMIN_LOCAL_MORE_APPS"]
    assert "g3w_plugins" in apps
    assert "portal" not in apps and "PORTAL_NAVBAR_TOP" not in context.docker_settings


@given("the published G3W Docker settings with the manager and portal disabled in isolated state")
def integration_settings(context):
    local_settings = Path("/code/g3w-admin/base/settings/local_settings.py")
    previous = local_settings.read_text(encoding="utf-8")
    context.add_cleanup(local_settings.write_text, previous, encoding="utf-8")
    local_settings.write_text(Path("/tmp/docker-settings.py").read_text(encoding="utf-8"), encoding="utf-8")
    Path("/shared-volume/media").mkdir(parents=True, exist_ok=True)
    Path("/shared-volume/project_data").mkdir(parents=True, exist_ok=True)
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    (Path(directory.name) / "state.json").write_text(json.dumps({
        "plugins": {"g3w-admin-portal": False}, "site": None,
    }), encoding="utf-8")
    context.docker_manage_env = dict(os.environ, G3W_PLUGINS_DIR=directory.name)
    manage(context, "migrate", "--noinput")
    assert "g3w-admin-panoramax: running=False, after_restart=None" in manage(context, "plugins", "list")


def manage(context, *args):
    result = subprocess.run(
        [sys.executable, "manage.py", *args], cwd="/code/g3w-admin",
        env=context.docker_manage_env, text=True, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(f"manage.py {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


@when("panoramax is enabled through the management command")
def enable_docker_plugin(context):
    manage(context, "plugins", "enable", "g3w-admin-panoramax")


@then("the plugin is active and its URL, template and sitetrees are available")
def docker_plugin_active(context):
    assert "g3w-admin-panoramax: running=True, after_restart=True" in manage(context, "plugins", "list")
    manage(
        context, "shell", "-c",
        "from django.urls import reverse; from django.template.loader import get_template; "
        "from g3w_plugins.sitetrees import sitetrees; "
        "assert 'plugins' in reverse('g3w-plugins'); "
        "assert get_template('plugins/index.html'); assert len(sitetrees) == 2",
    )


@when("panoramax is disabled through the management command")
def disable_docker_plugin(context):
    manage(context, "plugins", "disable", "g3w-admin-panoramax")


@then("the plugin is disabled after restart")
def docker_plugin_disabled(context):
    assert "g3w-admin-panoramax: running=False, after_restart=False" in manage(context, "plugins", "list")


def isolated_command(context, args):
    result = subprocess.run(
        args, cwd=context.uninstall_root, env=context.uninstall_env, text=True, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(f"Isolated command failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def isolated_apps(context):
    code = (
        "import json, sys; from base.settings import local_settings as s; "
        "print(json.dumps([s.G3WADMIN_LOCAL_MORE_APPS, sys.path]))"
    )
    return json.loads(isolated_command(context, [str(context.uninstall_python), "-c", code]))


@given("an isolated installed manager and a downloaded plugin")
def isolated_installation(context):
    temporary = tempfile.TemporaryDirectory()
    context.add_cleanup(temporary.cleanup)
    context.uninstall_root = Path(temporary.name)
    context.uninstall_env = dict(os.environ, PYTHONNOUSERSITE="1")
    for name in ("PYTHONPATH", "PYTHONHOME", "DJANGO_SETTINGS_MODULE", "G3W_PLUGINS_CANDIDATE"):
        context.uninstall_env.pop(name, None)
    environment = context.uninstall_root / "venv"
    isolated_command(context, [sys.executable, "-m", "venv", str(environment)])
    context.uninstall_python = environment / "bin" / "python"
    repository = Path(__file__).resolve().parents[3]
    isolated_command(context, [
        str(context.uninstall_python), "-m", "pip", "install", str(repository),
    ])
    settings = context.uninstall_root / "base" / "settings"
    settings.mkdir(parents=True)
    (settings.parent / "__init__.py").write_text("", encoding="utf-8")
    (settings / "__init__.py").write_text(
        "G3WADMIN_APPS = ['base']\nG3WADMIN_PROJECT_APPS_BASE = ['qdjango']\n"
        "from .local_settings import *\n", encoding="utf-8",
    )
    (settings / "local_settings.py").write_text("G3WADMIN_LOCAL_MORE_APPS = []\n", encoding="utf-8")
    data = context.uninstall_root / "data"
    site = data / ("site-" + "a" * 32)
    plugin = site / "panoramax"
    plugin.mkdir(parents=True)
    context.downloaded_file = plugin / "__init__.py"
    context.downloaded_file.write_text("# retained\n", encoding="utf-8")
    context.saved_state = data / "state.json"
    context.saved_state.write_text(json.dumps({
        "plugins": {"g3w-admin-panoramax": True}, "site": site.name,
    }), encoding="utf-8")
    context.uninstall_env["G3W_PLUGINS_DIR"] = str(data)
    context.downloaded_site = str(site)
    apps, paths = isolated_apps(context)
    assert "g3w_plugins" in apps and "panoramax" in apps and str(site) in paths


@when("the manager is uninstalled")
def uninstall_manager(context):
    isolated_command(context, [
        sys.executable, "-m", "pip", "--python", str(context.uninstall_python),
        "uninstall", "-y", "g3w-admin-plugins",
    ])


@then("the plugin files and state remain without automatic activation")
def uninstall_preserves_plugins(context):
    apps, paths = isolated_apps(context)
    assert "g3w_plugins" not in apps and "panoramax" not in apps
    assert context.downloaded_site not in paths
    assert context.downloaded_file.read_text(encoding="utf-8") == "# retained\n"
    assert json.loads(context.saved_state.read_text(encoding="utf-8"))["plugins"]["g3w-admin-panoramax"]

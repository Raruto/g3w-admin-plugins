import ast
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


def integrated_settings():
    source = Path("/tmp/docker-settings.py").read_text(encoding="utf-8")
    assignments = [
        node for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "G3WADMIN_LOCAL_MORE_APPS"
                for target in node.targets)
    ]
    if len(assignments) != 1:
        raise ValueError("Expected one G3WADMIN_LOCAL_MORE_APPS assignment in Docker settings")
    lines = source.splitlines(keepends=True)
    lines.insert(assignments[0].end_lineno, "\nfrom g3w_plugins.manager import configure\nconfigure(G3WADMIN_LOCAL_MORE_APPS)\n")
    return "".join(lines)


def docker_settings(environment, manager=True):
    import django.conf
    settings = SimpleNamespace(BASE_DIR="/code/g3w-admin", TEMPLATES=[{"DIRS": []}], STATICFILES_DIRS=[])
    source = integrated_settings() if manager else Path("/tmp/docker-settings.py").read_text(encoding="utf-8")
    result = {"__name__": "<run_path>", "__file__": "/tmp/docker-settings.py"}
    with patch.object(django.conf, "settings", settings), patch.dict(os.environ, environment, clear=True):
        exec(compile(source, "/tmp/docker-settings.py", "exec"), result)
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
        site.mkdir()
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
    local_settings.write_text(integrated_settings(), encoding="utf-8")
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

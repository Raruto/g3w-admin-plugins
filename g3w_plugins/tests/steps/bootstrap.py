import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from behave import given, then, when


@given('G3W settings with "{registration}" manager registration')
def settings_fixture(context, registration):
    root = tempfile.TemporaryDirectory()
    context.add_cleanup(root.cleanup)
    context.bootstrap_root = Path(root.name)
    settings = context.bootstrap_root / "base" / "settings"
    settings.mkdir(parents=True)
    (settings.parent / "__init__.py").write_text("", encoding="utf-8")
    g3w = "" if registration == "unrelated" else (
        "G3WADMIN_APPS = ['base']\nG3WADMIN_PROJECT_APPS_BASE = ['qdjango']\n"
    )
    (settings / "__init__.py").write_text(
        g3w +
        "from .local_settings import *\n"
        "SECRET_KEY = 'test'\n"
        "INSTALLED_APPS = G3WADMIN_LOCAL_MORE_APPS\n",
        encoding="utf-8",
    )
    selected = registration in ("initial", "manual-with-marker", "overwrite")
    late = registration == "late"
    apps = ["portal", "g3w_plugins"] if selected else ["portal"]
    if late:
        apps = []
    annotation = ": list[str]" if registration == "annotated" else ""
    assignment = f"G3WADMIN_LOCAL_MORE_APPS{annotation} = {apps!r}\n"
    source = f"if True:\n    {assignment}" if registration == "conditional" else assignment
    if late:
        source += "G3WADMIN_LOCAL_MORE_APPS.append('g3w_plugins')\n"
    if registration == "overwrite":
        source += "G3WADMIN_LOCAL_MORE_APPS.append('portal')\n"
    if registration in ("manual", "manual-with-marker"):
        source += (
            "from g3w_plugins.manager import configure\n"
            "configure(G3WADMIN_LOCAL_MORE_APPS)\n"
        )
    source += "PORTAL_CONFIGURED = 'portal' in G3WADMIN_LOCAL_MORE_APPS\n"
    (settings / "local_settings.py").write_text(source, encoding="utf-8")
    context.bootstrap_env = dict(os.environ, G3W_PLUGINS_DIR=str(context.bootstrap_root))
    context.bootstrap_env.pop("G3W_PLUGINS_CANDIDATE", None)
    project = Path(__file__).resolve().parents[3]
    context.bootstrap_env["PYTHONPATH"] = os.pathsep.join(
        [str(project), context.bootstrap_env.get("PYTHONPATH", "")]
    )


@given('portal is disabled in "{publication}" state')
def disabled_state(context, publication):
    state = {"plugins": {"g3w-admin-portal": False}, "site": None}
    candidate = publication == "candidate"
    path = context.bootstrap_root / (".state-test" if candidate else "state.json")
    path.write_text(json.dumps(state), encoding="utf-8")
    if candidate:
        context.bootstrap_env["G3W_PLUGINS_CANDIDATE"] = str(path)


@given("portal is enabled in an isolated installation")
def enabled_portal(context):
    site = "site-" + "a" * 32
    module = context.bootstrap_root / site / "portal"
    module.mkdir(parents=True)
    (module / "__init__.py").write_text("", encoding="utf-8")
    (context.bootstrap_root / "state.json").write_text(json.dumps({
        "plugins": {"g3w-admin-portal": True}, "site": site,
    }), encoding="utf-8")
    context.bootstrap_site = str(context.bootstrap_root / site)


@when("the G3W settings are imported with the startup hook")
def import_settings(context):
    code = (
        "import json; from g3w_plugins.bootstrap import install; install(); "
        "from base.settings import local_settings as s; "
        "import sys; print(json.dumps([s.G3WADMIN_LOCAL_MORE_APPS, s.PORTAL_CONFIGURED, sys.path]))"
    )
    context.bootstrap_result = subprocess.run(
        [sys.executable, "-c", code], cwd=context.bootstrap_root,
        env=context.bootstrap_env, text=True, capture_output=True,
    )


@then("portal and its settings are disabled")
def portal_disabled(context):
    assert context.bootstrap_result.returncode == 0, context.bootstrap_result.stderr
    apps, portal_configured, _ = json.loads(context.bootstrap_result.stdout)
    assert "g3w_plugins" in apps and "portal" not in apps
    assert portal_configured is False


@then("portal and its settings are enabled without the manager")
def portal_enabled_without_manager(context):
    assert context.bootstrap_result.returncode == 0, context.bootstrap_result.stderr
    apps, portal_configured, _ = json.loads(context.bootstrap_result.stdout)
    assert apps == ["portal"] and portal_configured is True


@then("portal and its settings are enabled with the manager")
def portal_enabled_with_manager(context):
    assert context.bootstrap_result.returncode == 0, context.bootstrap_result.stderr
    apps, portal_configured, _ = json.loads(context.bootstrap_result.stdout)
    assert apps == ["portal", "g3w_plugins"] and portal_configured is True


@then("the manager appears once in the imported settings")
def one_manager(context):
    assert context.bootstrap_result.returncode == 0, context.bootstrap_result.stderr
    apps, _, _ = json.loads(context.bootstrap_result.stdout)
    assert apps.count("g3w_plugins") == 1


@then("the plugin installation is on the Python path once")
def site_added_once(context):
    assert context.bootstrap_result.returncode == 0, context.bootstrap_result.stderr
    _, _, paths = json.loads(context.bootstrap_result.stdout)
    assert paths.count(context.bootstrap_site) == 1


@then("startup reports that the manager could not configure G3W")
def unsupported_settings(context):
    assert context.bootstrap_result.returncode != 0
    assert "The plugin manager could not configure G3W settings" in context.bootstrap_result.stderr


@then("startup reports that the portal state was overwritten")
def overwritten_state(context):
    assert context.bootstrap_result.returncode != 0
    assert "G3W settings overwrote the configured state of g3w-admin-portal" in context.bootstrap_result.stderr

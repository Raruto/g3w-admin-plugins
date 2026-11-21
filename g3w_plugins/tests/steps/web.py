import json
import os
import sys
from concurrent.futures import Future
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from behave import then, when
from django.conf import settings


def web_request(context, method, path="/", data=None, superuser=True, ajax=False):
    headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"} if ajax else {}
    request = getattr(context.factory, method)(path, data or {}, **headers)
    request.user = SimpleNamespace(is_active=True, is_superuser=superuser)
    return request


def template():
    from django.template import Engine
    source = (Path(__file__).resolve().parents[2] / "templates" / "plugins" / "index.html").read_text(
        encoding="utf-8"
    )
    return Engine(loaders=[("django.template.loaders.locmem.Loader", {
        "base.html": "{% block main_content %}{% endblock %}", "index.html": source,
    })]).get_template("index.html")


@when("the sidebar is filtered for users with different permissions")
def sidebar_filter(context):
    from g3w_plugins.apps import filter_plugin_menu
    items = [SimpleNamespace(url="g3w-plugins"), SimpleNamespace(url="other")]
    context.menu_results = []
    for active, superuser in ((True, True), (True, False), (False, True)):
        user = SimpleNamespace(is_active=active, is_superuser=superuser,
                               get_all_permissions=lambda: {"auth.change_user"})
        result = filter_plugin_menu(items, {"request": SimpleNamespace(user=user)})
        context.menu_results.append((items[0] in result, items[1] in result))
    context.empty_menu = filter_plugin_menu(items, {})
    context.other_item = items[1]


@then("only active superusers see the plugin entry")
def sidebar_restricted(context):
    assert context.menu_results == [(True, True), (False, True), (False, True)]
    assert context.empty_menu == [context.other_item]


@when("the plugin registers its sidebar hook twice")
def register_sidebar(context):
    from g3w_plugins.apps import PluginsConfig
    context.hook_results = []
    for arg_count in (2, 3):
        previous = lambda **kwargs: kwargs["tree_items"]
        sitetreeapp = SimpleNamespace(_ITEMS_PROCESSOR=previous, _ITEMS_PROCESSOR_ARGS_LEN=arg_count)
        sitetreeapp.register_items_hook = lambda hook: setattr(sitetreeapp, "_ITEMS_PROCESSOR", hook)
        config = PluginsConfig("g3w_plugins", sys.modules["g3w_plugins"])
        with patch.dict(sys.modules, {"sitetree": SimpleNamespace(sitetreeapp=sitetreeapp)}), \
                patch.dict(os.environ, {"G3WSUITE_CONSUMER": "1"}):
            config.ready()
            hook = sitetreeapp._ITEMS_PROCESSOR
            config.ready()
            same_hook = sitetreeapp._ITEMS_PROCESSOR is hook
        items = [SimpleNamespace(url="g3w-plugins"), SimpleNamespace(url="other")]
        context.hook_results.append((same_hook, hook(items, "menu", {}) == [items[1]]))


@then("the existing two-argument and three-argument hooks are preserved")
def sidebar_hooks(context):
    assert context.hook_results == [(True, True), (True, True)]


@when("the plugin initializes its application")
def initialize_application(context):
    from g3w_plugins.apps import PluginsConfig
    sitetreeapp = SimpleNamespace(_ITEMS_PROCESSOR=None, _ITEMS_PROCESSOR_ARGS_LEN=3)
    sitetreeapp.register_items_hook = lambda hook: setattr(sitetreeapp, "_ITEMS_PROCESSOR", hook)
    config = PluginsConfig("g3w_plugins", sys.modules["g3w_plugins"])
    with patch.dict(sys.modules, {"sitetree": SimpleNamespace(sitetreeapp=sitetreeapp)}), \
            patch.dict(os.environ, {"G3WSUITE_CONSUMER": "1"}), \
            TestCase().assertLogs("g3w_plugins.apps", level="INFO") as captured:
        config.ready()
    context.startup_records = captured.records


@then("an informational startup event is logged")
def startup_event(context):
    assert len(context.startup_records) == 1
    assert context.startup_records[0].levelname == "INFO"
    assert context.startup_records[0].getMessage() == "G3W plugin manager initialized"


@when("plugin application initialization fails")
def fail_application_initialization(context):
    from g3w_plugins.apps import PluginsConfig, logger
    sitetreeapp = SimpleNamespace(_ITEMS_PROCESSOR=None, _ITEMS_PROCESSOR_ARGS_LEN=3)
    config = PluginsConfig("g3w_plugins", sys.modules["g3w_plugins"])
    with patch.object(sitetreeapp, "register_items_hook", side_effect=RuntimeError("startup failed"),
                      create=True), \
            patch.dict(sys.modules, {"sitetree": SimpleNamespace(sitetreeapp=sitetreeapp)}), \
            patch.dict(os.environ, {"G3WSUITE_CONSUMER": "1"}), patch.object(logger, "info") as info:
        try:
            config.ready()
        except RuntimeError as error:
            assert str(error) == "startup failed"
        else:
            raise AssertionError("Startup should have failed")
    context.startup_info_calls = info.call_count


@then("no startup success event is logged")
def no_startup_event(context):
    assert context.startup_info_calls == 0


@when("status is requested for matching and outdated web configurations")
def worker_configuration(context):
    from g3w_plugins import views
    state = {"plugins": {"g3w-admin-panoramax": False}, "site": None}
    job = {"status": "succeeded", "reload": "requested", "target": views.fingerprint(state)}
    request = web_request(context, "get", "/status/")
    context.web_applied = []
    for configured in (state, {"plugins": {}, "site": None}):
        with patch.object(views.jobs, "status", return_value=job), \
                patch.object(views.manager, "configured_state", configured):
            context.web_applied.append(json.loads(views.job_status(request).content)["web_applied"])


@then("only the matching web configuration is confirmed")
def worker_confirmed(context):
    assert context.web_applied == [True, False]


@when("status is requested with the consumer disabled, pending and ready")
def consumer_status(context):
    from g3w_plugins import views
    state = {"plugins": {"g3w-admin-panoramax": False}, "site": None}
    job = {"status": "succeeded", "reload": "requested", "target": views.fingerprint(state),
           "plugin": "g3w-admin-panoramax", "reload_requested_at": 100}
    request = web_request(context, "get", "/status/")
    context.consumer_results = []
    for enabled, ready in ((False, False), (True, False), (True, True)):
        with patch.object(views.jobs, "status", return_value=job), \
                patch.object(views.manager, "configured_state", state), \
                patch.object(views, "consumer_enabled", return_value=enabled), \
                patch.object(views, "consumer_applied", return_value=ready), \
                patch.object(views.time, "time", return_value=120):
            data = json.loads(views.job_status(request).content)
        plugin = next(p for p in data["plugins"] if p["package"] == job["plugin"])
        context.consumer_results.append((data["web_applied"], data["consumer_required"],
                                         data["consumer_applied"], plugin["status"]))


@then("consumer flags and plugin status reflect each condition")
def consumer_confirmation(context):
    assert context.consumer_results == [
        (True, False, False, "Disabled"),
        (True, True, False, "Waiting for consumer reload"),
        (True, True, True, "Disabled"),
    ]


@when("a confirmed success is rendered in Italian")
def localized_success(context):
    from django.template import Context
    from django.utils import translation
    job = {"status": "succeeded", "reload": "requested", "plugin": "g3w-admin-portal",
           "action": "enable", "target": "abc", "reload_requested_at": 123.5}
    with translation.override("it"):
        html = template().render(Context({"job": job, "web_applied": True, "consumer_required": False}))
    context.alert = html.split('<div id="job-status"', 1)[1].split(">", 1)[0]


@then("the hidden notification retains the unlocalized timestamp")
def hidden_localized_success(context):
    assert 'data-requested-at="123.5"' in context.alert
    assert 'data-confirmed="true" hidden' in context.alert


@when("the frontend is enabled or disabled")
def frontend_paths(context):
    from g3w_plugins import views
    request = web_request(context, "get")
    context.alternates = []
    for frontend, status_url in ((True, "/en/admin/plugins/status/"), (False, "/en/plugins/status/")):
        with patch.object(settings, "FRONTEND", frontend, create=True), \
                patch.object(views, "reverse", return_value=status_url), \
                patch.object(views, "render") as render:
            views.index(request)
        context.alternates.append(render.call_args.args[2]["alternate_status_url"])


@then("the alternate status URL points to the other application path")
def alternate_paths(context):
    assert context.alternates == ["/en/plugins/status/", "/en/admin/plugins/status/"]


@when("one plugin has package metadata and another does not")
def installed_versions(context):
    from g3w_plugins import views

    def metadata(package):
        if package == "g3w-admin-panoramax":
            return "1.2.3"
        raise views.PackageNotFoundError(package)

    views.package_version.cache_clear()
    context.add_cleanup(views.package_version.cache_clear)
    with patch.object(views, "version", side_effect=metadata):
        plugins = json.loads(views.job_status(web_request(context, "get", "/status/")).content)["plugins"]
    context.versions = {plugin["package"]: plugin["version"] for plugin in plugins}


@then("their versions reflect the available metadata")
def versions_displayed(context):
    assert context.versions["g3w-admin-panoramax"] == "1.2.3"
    assert context.versions["g3w-admin-portal"] is None


class Buttons(HTMLParser):
    def __init__(self):
        super().__init__()
        self.actions = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "button" and attrs.get("value") in ("enable", "disable"):
            self.actions.append(attrs)


@when("plugin rows are rendered for running and desired states")
def render_actions(context):
    from django.template import Context
    from g3w_plugins import views
    context.rendered_actions = []
    for running, desired in ((False, None), (True, None), (False, True), (True, False)):
        plugins = {} if desired is None else {"g3w-admin-panoramax": desired}
        apps = ["panoramax"] if running else []
        with patch.object(views, "read_state", return_value={"plugins": plugins}), \
                patch.object(settings, "G3WADMIN_LOCAL_MORE_APPS", apps):
            plugin = next(p for p in views.plugin_status() if p["package"] == "g3w-admin-panoramax")
        html = template().render(Context({"plugins": [plugin], "job": {"status": "running"},
                                          "csrf_token": "test"}))
        buttons = Buttons()
        buttons.feed(html)
        context.rendered_actions.append((buttons.actions, html))


@then("each row shows exactly one disabled action and the correct status")
def correct_actions(context):
    for (buttons, html), (action, status) in zip(context.rendered_actions, (
        ("enable", "Disabled"), ("disable", "Running"),
        ("disable", "Enable pending reload"), ("enable", "Disable pending reload"),
    )):
        assert len(buttons) == 1
        assert buttons[0]["value"] == action and "disabled" in buttons[0]
        assert f'<td class="plugin-status">{status}</td>' in html


@when("a plugin is updated through each preparation and reload phase")
def row_phases(context):
    from g3w_plugins import views
    plugin = {"package": "g3w-admin-panoramax", "running": True, "desired": True}
    job = {"plugin": plugin["package"], "status": "running", "action": "update"}
    context.phase_results = [
        views.display_status(plugin, dict(job, phase=phase), False, 120)
        for phase in ("starting", "install", "migrate", "collectstatic", "sitetree_resync_apps", "save", "reload")
    ]
    requested = dict(job, status="succeeded", reload="requested", reload_requested_at=100)
    context.reload_results = [
        views.display_status(plugin, dict(job, status="failed"), False, 120),
        views.display_status(plugin, dict(job, status="reload_failed"), False, 120),
        views.display_status(plugin, requested, False, 120),
        views.display_status(plugin, requested, False, 160),
        views.display_status(plugin, requested, True, 160),
        views.display_status(plugin, dict(job, status="succeeded", reload="manual"), False, 120),
        views.display_status(dict(plugin, package="other"), job, False, 120),
    ]


@then("the row describes its current phase, failure or reload state")
def correct_row_phases(context):
    assert context.phase_results == ["Updating", "Installing packages", "Applying migrations",
                                     "Collecting static files", "Updating menus", "Saving configuration",
                                     "Requesting reload"]
    assert context.reload_results == ["Operation failed", "Reload failed", "Waiting for web reload",
                                     "Reload not confirmed", "Running", "Reload required", "Running"]


@when("an asynchronous activation is rejected as already running")
def async_rejected(context):
    from g3w_plugins import views
    request = web_request(context, "post", data={"action": "enable", "plugin": "g3w-admin-panoramax"}, ajax=True)
    with patch.object(views.jobs, "start", side_effect=RuntimeError("already running")):
        context.response = views.index(request)


@then("the response contains the rejection")
def rejection_response(context):
    assert context.response.status_code == 400
    assert json.loads(context.response.content)["error"] == "already running"


@when("a version check completes, is pending or fails")
def version_checks(context):
    from g3w_plugins import views
    request = web_request(context, "get", "/version/", {"plugin": "g3w-admin-panoramax"}, superuser=False)
    context.denied = views.latest_version(request).status_code
    request.user.is_superuser = True
    views.version_checks.clear()
    context.add_cleanup(views.version_checks.clear)
    with patch.object(views, "urlopen", return_value=BytesIO(b'{"info":{"version":"1.10"}}')):
        context.fetched = views.fetch_latest_version("g3w-admin-panoramax")
    future = Future()
    future.set_result("1.10")
    with patch.object(views, "package_version", return_value="1.9"), \
            patch.object(views.version_executor, "submit", return_value=future):
        context.available = json.loads(views.latest_version(request).content)
    with patch.object(views, "package_version", return_value=None):
        context.unknown = json.loads(views.latest_version(request).content)
    views.version_checks.clear()
    future = Future()
    with patch.object(views, "package_version", return_value="1.9"), \
            patch.object(views.version_executor, "submit", return_value=future):
        context.pending = views.latest_version(request).status_code
        future.set_exception(OSError("network unavailable"))
        context.failed_response = views.latest_version(request)
    context.invalid = views.latest_version(
        web_request(context, "get", "/version/", {"plugin": "../invalid"})
    ).status_code


@then("access, versions, errors and invalid plugin names are handled correctly")
def version_results(context):
    assert context.denied == 302 and context.fetched == "1.10"
    assert context.available == {"installed": "1.9", "latest": "1.10", "available": True}
    assert context.unknown == {"installed": None, "latest": "1.10", "available": False}
    assert context.pending == 202 and context.failed_response.status_code == 502
    assert "network unavailable" in json.loads(context.failed_response.content)["error"]
    assert context.invalid == 400


@when("a superuser requests version 1.10 of panoramax")
def selected_version(context):
    from g3w_plugins import views
    request = web_request(context, "post", data={
        "action": "update", "plugin": "g3w-admin-panoramax", "version": "1.10",
    }, ajax=True)
    with patch.object(views.jobs, "available", return_value=True), patch.object(views.jobs, "start") as start:
        context.response = views.index(request)
    context.start_args = start.call_args


@then("the update job receives that version")
def version_forwarded(context):
    assert context.response.status_code == 200
    assert context.start_args.args == ("g3w-admin-panoramax", "update", "1.10")


@when("editing and qplotly are configured with qes installed")
def bundled_status(context):
    from g3w_plugins import views
    with patch.object(settings, "G3WADMIN_LOCAL_MORE_APPS", ["editing", "qplotly"]), \
            patch.object(views.apps, "is_installed", return_value=True), \
            patch.object(views, "package_version", return_value=None):
        context.plugins = json.loads(views.job_status(web_request(context, "get", "/status/")).content)["plugins"]


@then("bundled modules, warnings and sorted display names are reported")
def bundled_reported(context):
    rows = {plugin["package"]: plugin for plugin in context.plugins}
    assert rows["editing"]["bundled"] and rows["editing"]["running"]
    assert "qes requires editing" in rows["editing"]["warning"]
    assert not rows["filemanager"]["running"] and not rows["g3w-admin-portal"]["bundled"]
    assert rows["editing"]["display_name"] == "g3w-admin-editing"
    names = [plugin["display_name"] for plugin in context.plugins]
    assert names == sorted(names)
    assert names.index("g3w-admin-editing") < names.index("g3w-admin-panoramax")


@when("a superuser requests an editing update or version check")
def bundled_pypi_requests(context):
    from g3w_plugins import views
    update = web_request(context, "post", data={"action": "update", "plugin": "editing", "version": "2.0"},
                         ajax=True)
    with patch.object(views.jobs, "start") as start:
        context.update_code = views.index(update).status_code
    with patch.object(views.version_executor, "submit") as submit:
        context.version_code = views.latest_version(
            web_request(context, "get", "/version/", {"plugin": "editing"})
        ).status_code
    context.calls = (start.call_count, submit.call_count)


@then("both requests are rejected without starting work")
def bundled_pypi_rejected(context):
    assert (context.update_code, context.version_code) == (400, 400)
    assert context.calls == (0, 0)


@when("a superuser disables editing with qes installed")
def editing_web(context):
    from g3w_plugins import views
    request = web_request(context, "post", data={"action": "disable", "plugin": "editing"}, ajax=True)
    with patch.object(views.jobs, "available", return_value=True), \
            patch.object(views.apps, "is_installed", return_value=True), \
            patch.object(views.jobs.subprocess, "Popen") as process:
        context.response = views.index(request)
    context.process_calls = process.call_count


@then("the dependency error is returned without starting a process")
def editing_web_rejected(context):
    assert context.response.status_code == 400
    assert "qes requires editing" in json.loads(context.response.content)["error"]
    assert context.process_calls == 0


@when("the CLI disables editing with qes installed")
def editing_cli(context):
    from django.core.management.base import CommandError
    from g3w_plugins import views
    from g3w_plugins.management.commands.plugins import Command
    command = Command()
    options = command.create_parser("manage.py", "plugins").parse_args(["disable", "editing"])
    with patch.object(views.apps, "is_installed", return_value=True):
        try:
            command.handle(**vars(options))
        except CommandError as error:
            context.cli_error = str(error)
        else:
            raise AssertionError("CLI accepted disabling editing")


@then("the CLI reports the dependency error")
def editing_cli_rejected(context):
    assert "qes requires editing" in context.cli_error


@when("the editing row is rendered with qes installed")
def editing_row(context):
    from django.template import Context
    from g3w_plugins import views
    with patch.object(settings, "G3WADMIN_LOCAL_MORE_APPS", ["editing"]), \
            patch.object(views.apps, "is_installed", return_value=True):
        plugin = next(p for p in views.plugin_status() if p["package"] == "editing")
    html = template().render(Context({"plugins": [plugin], "VERSION": "4.0.test"}))
    context.row = html.split('<tr data-plugin="editing"', 1)[1].split("</tr>", 1)[0]


@then("it shows the bundled source and warning without PyPI controls")
def bundled_row(context):
    for text in ("4.0.test", 'href="https://github.com/g3w-suite/g3w-admin/tree/dev/g3w-admin/editing"',
                 "g3w-admin-editing", 'name="plugin" value="editing"', "qes requires editing",
                 'data-blocked="true"', "disabled"):
        assert text in context.row
    assert "pypi.org" not in context.row and "plugin-update" not in context.row

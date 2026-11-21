import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from behave import given, then, when
from django.conf import settings


@given("an isolated plugin administration request")
def isolated_web(context):
    if not settings.configured:
        settings.configure(
            SECRET_KEY="test",
            ROOT_URLCONF="g3w_plugins.urls",
            LOGIN_URL="/login/",
            G3WADMIN_LOCAL_MORE_APPS=["g3w_plugins"],
            ALLOWED_HOSTS=["testserver"],
            INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes"],
        )
    import django
    django.setup()
    from django.test import RequestFactory

    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    environment = patch.dict(os.environ, {"G3W_PLUGINS_DIR": directory.name})
    environment.start()
    context.add_cleanup(environment.stop)
    context.factory = RequestFactory()


def request(context, method, path="/", data=None, superuser=True, ajax=False):
    options = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"} if ajax else {}
    result = getattr(context.factory, method)(path, data or {}, **options)
    result.user = SimpleNamespace(is_active=True, is_superuser=superuser)
    return result


@when("a non-superuser requests or changes the plugin page")
def non_superuser_requests(context):
    from g3w_plugins import views
    context.responses = []
    with patch.object(views.jobs, "start") as start, patch.object(views, "change") as change:
        for method in ("get", "post"):
            context.responses.append(views.index(request(
                context, method, data={"action": "enable", "plugin": "g3w-admin-panoramax"},
                superuser=False,
            )).status_code)
    context.calls = (start.call_count, change.call_count)


@then("both requests are redirected without starting a change")
def unauthorized_redirected(context):
    assert context.responses == [302, 302]
    assert context.calls == (0, 0)


@when("a superuser submits a change without a CSRF token")
def no_csrf(context):
    from django.middleware.csrf import CsrfViewMiddleware
    from g3w_plugins import views
    submitted = request(context, "post", data={"action": "enable", "plugin": "g3w-admin-panoramax"})
    context.response = CsrfViewMiddleware(lambda request: None).process_view(submitted, views.index, (), {})


@then("CSRF middleware rejects the request")
def csrf_rejected(context):
    assert context.response.status_code == 403


@when("a superuser enables panoramax")
def enable_plugin(context):
    from g3w_plugins import views
    submitted = request(context, "post", data={"action": "enable", "plugin": "g3w-admin-panoramax"})
    with patch.object(views.jobs, "available", return_value=True), \
            patch.object(views.jobs, "start") as start, patch.object(views.messages, "success"):
        context.response = views.index(submitted)
    context.start_args = start.call_args


@then("background preparation starts for panoramax")
def background_started(context):
    assert context.response.status_code == 302
    assert context.start_args.args == ("g3w-admin-panoramax", "enable")


@when("a superuser submits untrusted plugin names")
def unsafe_plugins(context):
    from g3w_plugins import views
    context.responses = []
    with patch.object(views.jobs, "start") as start, patch.object(views, "change") as change:
        for background in (True, False):
            for name in ("evil-plugin", "g3w-admin-portal[evil]", "--index-url=https://evil.invalid"):
                submitted = request(context, "post", data={"action": "enable", "plugin": name}, ajax=True)
                with patch.object(views.jobs, "available", return_value=background):
                    context.responses.append(views.index(submitted).status_code)
    context.calls = (start.call_count, change.call_count)


@then("the requests are rejected without starting preparation")
def unsafe_plugins_rejected(context):
    assert context.responses == [400] * 6
    assert context.calls == (0, 0)


@when("a superuser disables panoramax without background support")
def disable_synchronously(context):
    from g3w_plugins import views
    submitted = request(context, "post", data={"action": "disable", "plugin": "g3w-admin-panoramax"})
    with patch.object(views.jobs, "available", return_value=False), \
            patch.object(views, "change") as change, patch.object(views.messages, "success"):
        context.response = views.index(submitted)
    context.change_args = change.call_args


@then("synchronous preparation is invoked")
def synchronous_change(context):
    from g3w_plugins import views
    assert context.response.status_code == 302
    assert context.change_args.args == ("g3w-admin-panoramax", False)
    assert context.change_args.kwargs == {"prepare": views.prepare}


@when("a non-superuser and a superuser request a failing reload")
def failing_reload(context):
    from g3w_plugins import views
    unauthorized = request(context, "post", data={"action": "reload"}, superuser=False)
    authorized = request(context, "post", data={"action": "reload"})
    with patch.object(views.jobs, "retry_reload") as retry:
        context.unauthorized = views.index(unauthorized).status_code
    context.unauthorized_calls = retry.call_count
    with patch.object(views.jobs, "retry_reload", side_effect=RuntimeError("unavailable")), \
            patch.object(views.messages, "error") as error:
        context.authorized = views.index(authorized).status_code
    context.error_args = error.call_args
    context.authorized_request = authorized


@then("the non-superuser is redirected and the failure is reported")
def reload_failure_reported(context):
    assert context.unauthorized == 302
    assert context.unauthorized_calls == 0
    assert context.authorized == 302
    assert context.error_args.args == (context.authorized_request, "unavailable")


@when("a superuser requests reload during preparation")
def reload_during_preparation(context):
    from g3w_plugins import views
    submitted = request(context, "post", data={"action": "reload"})
    with patch.object(views.jobs, "lock_job", side_effect=BlockingIOError), \
            patch.object(views.jobs, "request_reload") as reload, \
            patch.object(views.messages, "error") as error:
        context.response = views.index(submitted)
    context.calls = (reload.call_count, error.call_count)


@then("reload is not requested and an error is reported")
def locked_reload_rejected(context):
    assert context.response.status_code == 302
    assert context.calls == (0, 1)


@when("a non-superuser and a superuser request status")
def status_requests(context):
    from g3w_plugins import views
    context.unauthorized = views.job_status(request(context, "get", "/status/", superuser=False)).status_code
    with patch.object(views.jobs, "status", return_value={
        "status": "running", "plugin": "g3w-admin-panoramax", "phase": "collectstatic",
    }):
        context.response = views.job_status(request(context, "get", "/status/"))


@then("only the superuser sees the preparation phase and an uncached response")
def status_restricted(context):
    assert context.unauthorized == 302
    data = json.loads(context.response.content)
    assert data["job"]["phase"] == "collectstatic"
    assert len(data["plugins"]) == 11
    plugin = next(p for p in data["plugins"] if p["package"] == "g3w-admin-panoramax")
    assert plugin["status"] == "Collecting static files"
    assert context.response["Cache-Control"] == "no-store"

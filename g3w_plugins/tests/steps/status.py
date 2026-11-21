import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from behave import given, then, when
from playwright.sync_api import expect, sync_playwright


@given("a completed preparation waiting for reload")
def completed_preparation(context):
    template = (Path(__file__).resolve().parents[2] / "templates" / "plugins" / "index.html").read_text(
        encoding="utf-8"
    )
    script = template.split("<script>", 1)[1].split("</script>", 1)[0]
    script = script.replace("{{ status_url|escapejs }}", "/status")
    script = script.replace("{{ alternate_status_url|escapejs }}", "")
    script = script.replace("{{ version_url|escapejs }}", "/version")
    html = (
        '<div id="job-status"{confirmed}></div><div id="job-progress"></div>'
        '<button class="job-action"></button>'
        '<div id="manual-reload"><button class="job-action"></button></div>'
        "<script>" + script + "</script>"
    )
    context.status = {
        "job": {"status": "succeeded", "reload": "requested", "plugin": "test",
                "action": "enable", "reload_requested_at": 100},
        "plugins": [], "web_applied": True, "consumer_required": True,
        "consumer_applied": False, "server_time": 120,
    }
    context.server_confirmed = False

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/status":
                content_type = "application/json"
                body = json.dumps(context.status).encode()
            else:
                content_type = "text/html"
                confirmed = (' data-confirmed="true" data-plugin="test" data-action="enable"'
                             ' data-target="" data-requested-at="100" hidden') if context.server_confirmed else ""
                body = html.replace("{confirmed}", confirmed).encode()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    context.add_cleanup(server.server_close)
    context.add_cleanup(server.shutdown)
    context.url = f"http://127.0.0.1:{server.server_port}/"
    playwright = sync_playwright().start()
    context.add_cleanup(playwright.stop)
    browser = getattr(playwright, context.config.userdata.get("browser", "chromium")).launch()
    context.add_cleanup(browser.close)
    context.page = browser.new_page()


@when('the status reports web "{web}", consumer "{consumer}", consumer required "{required}" after {seconds:d} seconds')
def report_status(context, web, consumer, required, seconds):
    context.status.update(web_applied=web == "true", consumer_applied=consumer == "true",
                          consumer_required=required == "true", server_time=100 + seconds)
    context.page.goto(context.url)
    expect(context.page.locator("#job-status")).not_to_be_empty()


@then('the status contains "{message}" with level "{level}"')
def status_message(context, message, level):
    status = context.page.locator("#job-status")
    expect(status).to_contain_text(message)
    expect(status).to_have_class(f"alert alert-{level}")


@then('actions are "{actions}" and retry is "{retry}"')
def available_actions(context, actions, retry):
    action = context.page.locator("button.job-action").first
    if actions == "disabled":
        expect(action).to_be_disabled()
    else:
        expect(action).to_be_enabled()
    reload = context.page.locator("#manual-reload")
    if retry == "hidden":
        expect(reload).to_be_hidden()
    else:
        expect(reload).to_be_visible()
        expect(reload.locator("button")).to_be_enabled()


@then("the success message is visible")
def visible_success(context):
    expect(context.page.locator("#job-status")).to_be_visible()


@then("the success message is hidden")
def hidden_success(context):
    expect(context.page.locator("#job-status")).to_be_hidden()


@when("the page is reloaded")
def reload_page(context):
    context.page.reload()
    expect(context.page.locator("#job-status")).to_be_hidden()


@when("the next status poll completes")
def poll_again(context):
    with context.page.expect_response("**/status"):
        pass


@when("a new preparation is confirmed")
def new_preparation(context):
    context.status["job"]["reload_requested_at"] = 101
    context.server_confirmed = False
    context.page.reload()
    expect(context.page.locator("#job-status")).to_contain_text("Web and consumer loaded")


@when("preparation fails")
def failed_preparation(context):
    context.status["job"].update(status="failed", error="failure")
    context.page.reload()


@when("the consumer is pending again")
def pending_consumer(context):
    context.status["consumer_applied"] = False
    context.page.reload()


@when("the server renders a confirmed success during a simulated reload")
def server_confirmed_reload(context):
    context.server_confirmed = True
    context.status["consumer_applied"] = True
    context.page.add_init_script(
        "Object.defineProperty(performance, 'getEntriesByType', "
        "{value: () => [{type: 'reload'}]});"
    )
    with context.page.expect_response("**/status"):
        context.page.goto(context.url)
    expect(context.page.locator("#job-progress")).to_be_hidden()

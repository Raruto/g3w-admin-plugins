"""Expose superuser plugin actions, status and PyPI version checks."""

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
import json
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from packaging.version import InvalidVersion, Version

from . import jobs
from . import manager
from .manager import BUNDLED, CATALOG, MANAGED, change, read_state
from .reload import available, consumer_applied, consumer_enabled, fingerprint, prepare


version_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="plugin-version")
version_lock = threading.Lock()
version_checks = {}


@user_passes_test(lambda user: user.is_active and user.is_superuser)
@require_http_methods(["GET", "POST"])
def index(request):
    if request.method == "POST":
        name = request.POST.get("plugin", "")
        action = request.POST.get("action", "")
        try:
            if action == "reload":
                jobs.retry_reload()
            elif action in ("enable", "disable", "update"):
                manager.validate_change(name, action != "disable")
                update_version = request.POST.get("version", "") if action == "update" else None
                if action == "update" and not update_version:
                    raise ValueError("An update version is required")
                if action == "update" and name not in CATALOG:
                    raise ValueError("Only PyPI plugins can be updated here")
                if jobs.available():
                    if action == "update":
                        jobs.start(name, action, update_version)
                    else:
                        jobs.start(name, action)
                else:
                    if action == "update":
                        change(name, True, prepare=prepare, update_version=update_version,
                               unmanaged_enabled=CATALOG.get(name) in settings.G3WADMIN_LOCAL_MORE_APPS)
                    else:
                        change(name, action == "enable", prepare=prepare)
            else:
                raise ValueError("Invalid action")
        except (ValueError, RuntimeError, OSError) as error:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"error": str(error)}, status=400)
            messages.error(request, str(error))
        else:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"ok": True})
            if action == "reload":
                messages.success(request, "Reload requested. Refresh this page after a few seconds.")
            elif jobs.available():
                messages.success(request, "Preparation started.")
            else:
                messages.success(request, "Saved and prepared. Reload G3W-SUITE and its consumer to apply.")
        return redirect("g3w-plugins")

    status_url = reverse("g3w-plugins-status")
    suffix = "plugins/status/"
    alternate = ""
    if status_url.endswith(suffix):
        prefix = status_url[:-len(suffix)]
        if getattr(settings, "FRONTEND", False) and prefix.endswith("admin/"):
            alternate = prefix[:-len("admin/")] + suffix
        elif not getattr(settings, "FRONTEND", False):
            alternate = prefix + "admin/" + suffix
    job, web_applied, consumer_required, consumer_ready, now = job_context()
    return render(request, "plugins/index.html", {
        "plugins": plugin_status(job, web_applied, now, consumer_required, consumer_ready),
        "reload_available": available(), "job": job, "web_applied": web_applied,
        "consumer_required": consumer_required, "consumer_applied": consumer_ready,
        "status_url": status_url, "alternate_status_url": alternate,
        "version_url": reverse("g3w-plugins-version"),
    })


@lru_cache(maxsize=len(CATALOG))
def package_version(package):
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def plugin_status(job=None, web_applied=False, now=None, consumer_required=False, consumer_ready=False):
    if now is None:
        now = time.time()
    desired = read_state()["plugins"]
    plugins = [
        {
            "package": package,
            "display_name": f"g3w-admin-{package}" if package in BUNDLED else package,
            "app": app,
            "running": app in settings.G3WADMIN_LOCAL_MORE_APPS,
            "desired": desired.get(package),
            "enabled": desired.get(package, app in settings.G3WADMIN_LOCAL_MORE_APPS),
            "version": package_version(package) if package in CATALOG else None,
            "bundled": package in BUNDLED,
            "warning": (
                "qes requires editing. Disable qes before disabling editing."
                if package == "editing" and desired.get(package, app in settings.G3WADMIN_LOCAL_MORE_APPS)
                and apps.is_installed("qes") else ""
            ),
        }
        for package, app in MANAGED.items()
    ]
    plugins.sort(key=lambda plugin: plugin["display_name"])
    for plugin in plugins:
        plugin["status"] = display_status(plugin, job, web_applied, now, consumer_required, consumer_ready)
    return plugins


def display_status(plugin, job, web_applied, now, consumer_required=False, consumer_ready=False):
    if job and job.get("plugin") == plugin["package"]:
        if job["status"] == "running":
            phases = {
                "install": "Installing packages",
                "migrate": "Applying migrations",
                "collectstatic": "Collecting static files",
                "sitetree_resync_apps": "Updating menus",
                "save": "Saving configuration",
                "reload": "Requesting reload",
            }
            actions = {"enable": "Enabling", "disable": "Disabling", "update": "Updating"}
            return phases.get(job.get("phase"), actions.get(job.get("action"), "Preparing"))
        if job["status"] == "failed":
            return "Operation failed"
        if job["status"] == "reload_failed":
            return "Reload failed"
        if job["status"] == "succeeded" and not web_applied:
            if job.get("reload") == "requested":
                requested_at = job.get("reload_requested_at")
                if requested_at and now - requested_at < 60:
                    return "Waiting for web reload"
                return "Reload not confirmed"
            return "Reload required"
        if (job["status"] == "succeeded" and job.get("reload") == "requested"
                and consumer_required and not consumer_ready):
            requested_at = job.get("reload_requested_at")
            if requested_at and now - requested_at < 60:
                return "Waiting for consumer reload"
            return "Consumer reload not confirmed"
    if plugin["desired"] is not None and plugin["desired"] != plugin["running"]:
        return "Enable pending reload" if plugin["desired"] else "Disable pending reload"
    return "Running" if plugin["running"] else "Disabled"


def fetch_latest_version(package):
    req = Request(f"https://pypi.org/pypi/{package}/json",
                  headers={"User-Agent": "g3w-admin-plugins"})
    with urlopen(req, timeout=8) as response:
        content = response.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise ValueError("PyPI response is too large")
    latest = json.loads(content)["info"]["version"]
    newest = Version(latest)
    if newest.is_prerelease or newest.is_devrelease:
        raise ValueError("PyPI did not return a stable release")
    return latest


@user_passes_test(lambda user: user.is_active and user.is_superuser)
@require_http_methods(["GET"])
def latest_version(request):
    package = request.GET.get("plugin", "")
    if package not in CATALOG:
        return JsonResponse({"error": "Unknown plugin"}, status=400)
    installed = package_version(package)
    with version_lock:
        entry = version_checks.get(package)
        if not entry or (entry[0].done() and time.monotonic() - entry[1] > 300):
            entry = (version_executor.submit(fetch_latest_version, package), time.monotonic())
            version_checks[package] = entry
    future = entry[0]
    if not future.done():
        response = JsonResponse({"status": "checking"}, status=202)
        response["Cache-Control"] = "no-store"
        return response
    try:
        latest = future.result()
        newest = Version(latest)
        current = Version(installed) if installed else None
    except (OSError, URLError, ValueError, KeyError, TypeError) as error:
        with version_lock:
            if version_checks.get(package) is entry:
                del version_checks[package]
        return JsonResponse({"error": f"Could not check PyPI: {error}"}, status=502)
    response = JsonResponse({"installed": installed, "latest": latest,
                             "available": current is not None and newest > current})
    response["Cache-Control"] = "no-store"
    return response


def job_context():
    job = jobs.status()
    now = time.time()
    target = job.get("target") if job else None
    if job and job["status"] == "succeeded" and "reload" not in job:
        target = fingerprint(read_state())
    web_applied = bool(
        target and manager.configured_state is not None
        and fingerprint(manager.configured_state) == target
    )
    consumer_required = consumer_enabled()
    consumer_ready = bool(
        consumer_required and job and job.get("reload") == "requested"
        and consumer_applied(target, job.get("reload_requested_at"), now)
    )
    return job, web_applied, consumer_required, consumer_ready, now


@user_passes_test(lambda user: user.is_active and user.is_superuser)
@require_http_methods(["GET"])
def job_status(request):
    job, web_applied, consumer_required, consumer_ready, now = job_context()
    response = JsonResponse({
        "job": job, "plugins": plugin_status(job, web_applied, now, consumer_required, consumer_ready),
        "web_applied": web_applied, "consumer_required": consumer_required, "consumer_applied": consumer_ready,
        "manager_url": reverse("g3w-plugins"), "server_time": now,
    })
    response["Cache-Control"] = "no-store"
    return response

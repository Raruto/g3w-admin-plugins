"""Maintain the plugin catalog, isolated installations and desired application state."""

import contextlib
import importlib.machinery
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from packaging.version import InvalidVersion, Version


CATALOG = {
    "g3w-admin-authjwt": "authjwt",
    "g3w-admin-panoramax": "panoramax",
    "g3w-admin-pdnd": "qpdnd",
    "g3w-admin-portal": "portal",
    "g3w-admin-processing": "qprocessing",
    "g3w-admin-ps-timeseries": "qps_timeseries",
    "g3w-admin-sentry-monitor": "sentry_monitor",
}
BUNDLED = {name: name for name in ("editing", "filemanager", "qplotly", "qtimeseries")}
MANAGED = {**CATALOG, **BUNDLED}

DOCKER_PLUGIN_DIR = Path("/shared-volume/.g3w_plugins")

configured_state = None


def in_docker():
    return Path("/.dockerenv").is_file()


def directory():
    """Resolve the persistent state directory and propagate a default to subprocesses."""
    value = os.environ.get("G3W_PLUGINS_DIR")
    if not value:
        default = DOCKER_PLUGIN_DIR if in_docker() else Path.home() / ".g3w_plugins"
        value = str(default.resolve())
        os.environ["G3W_PLUGINS_DIR"] = value
    return Path(value).resolve()


def read_state(path=None):
    """Read and validate a published or candidate state; missing state preserves existing apps."""
    path = path or directory() / "state.json"
    if not path.exists():
        return {"plugins": {}, "site": None}
    with path.open(encoding="utf-8") as file:
        state = json.load(file)
    if (
        not isinstance(state, dict)
        or not isinstance(state.get("plugins"), dict)
        or any(name not in MANAGED or type(enabled) is not bool
               for name, enabled in state["plugins"].items())
        or (state.get("site") is not None
            and (not isinstance(state["site"], str)
                 or not state["site"].startswith("site-")
                 or len(state["site"]) != 37
                 or any(c not in "0123456789abcdef" for c in state["site"][5:])))
        or (any(enabled for name, enabled in state["plugins"].items() if name in CATALOG)
            and state.get("site") is None)
    ):
        raise ValueError(f"Invalid plugin state: {path}")
    return state


@contextlib.contextmanager
def locked(root, blocking=True):
    """Serialize configuration changes across processes sharing the state directory."""
    root.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        from .windows_locks import Lock
        with Lock(root, "change", blocking) as lock:
            yield lock
        return
    with (root / ".lock").open("a+b") as lock:
        import fcntl
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield lock
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def child_lock_options(lock):
    """Keep the change and background-job locks alive in preparation subprocesses."""
    if os.name == "nt":
        from .windows_locks import inherited
        handles = [lock.handle]
        job_handle = os.environ.get("G3W_PLUGINS_JOB_HANDLE")
        if job_handle:
            handles.append(int(job_handle))
        with inherited(handles) as options:
            yield options
    else:
        job_fd = os.environ.get("G3W_PLUGINS_JOB_FD")
        yield {"pass_fds": (lock.fileno(),) + ((int(job_fd),) if job_fd else ())}


def normalized(name):
    return name.lower().replace("_", "-").replace(".", "-")


def spec_in_directory(spec, directory):
    if spec is None:
        return False
    paths = [spec.origin] if spec.origin is not None else spec.submodule_search_locations or []
    return bool(paths) and all(Path(path).resolve().is_relative_to(directory) for path in paths)


def validate_change(name, enabled):
    if name not in MANAGED:
        raise ValueError(f"Unknown plugin: {name}")
    if name == "editing" and not enabled:
        from django.apps import apps
        if not apps.ready:
            raise RuntimeError("Django must be initialized to check dependencies before disabling editing")
        if apps.is_installed("qes"):
            raise RuntimeError("qes requires editing. Disable qes before disabling editing.")


def change(name, enabled, prepare=None, progress=None, update_version=None, unmanaged_enabled=False):
    """Prepare a change under lock and publish its candidate state only after preparation succeeds.

    Preparation may change the database or static files even if publication fails. Installed
    package directories are retained for workers still using the previous configuration.
    """
    validate_change(name, enabled)
    if update_version is not None and name in BUNDLED:
        raise ValueError("Bundled modules are updated with G3W-SUITE, not PyPI")
    root = directory()
    with locked(root) as lock:
        state = read_state()
        if name in BUNDLED and enabled:
            try:
                available = importlib.util.find_spec(name) is not None
            except (ImportError, ValueError) as error:
                raise RuntimeError(f"Cannot locate bundled module {name}: {error}") from error
            if not available:
                raise RuntimeError(f"Bundled module {name} is not available in this G3W-SUITE installation")
        if update_version is not None:
            if not state["plugins"].get(name, unmanaged_enabled):
                raise ValueError("Only enabled plugins can be updated")
            try:
                requested = Version(update_version)
            except InvalidVersion as error:
                raise ValueError("Invalid update version") from error
            if requested.is_prerelease or requested.is_devrelease:
                raise ValueError("Only stable plugin releases can be installed")
            if name in state["plugins"]:
                site = root / state["site"]
                versions = {
                    normalized(dist.metadata["Name"]): dist.version
                    for dist in importlib.metadata.distributions(path=[str(site)])
                    if dist.metadata.get("Name")
                }
                current = versions.get(name)
            else:
                try:
                    current = importlib.metadata.version(name)
                except importlib.metadata.PackageNotFoundError:
                    current = None
                versions = {}
            try:
                if not current or requested <= Version(current):
                    raise ValueError("The requested version is not newer than the installed version")
            except InvalidVersion as error:
                raise ValueError("The installed plugin version is invalid") from error
        state["plugins"][name] = enabled
        selected = [plugin for plugin, active in state["plugins"].items() if active and plugin in CATALOG]
        if enabled and name in CATALOG:
            if progress:
                progress("install")
            site = "site-" + uuid.uuid4().hex
            target = root / site
            # Keep G3W's existing dependency versions; incompatible plugins fail installation.
            constraints = root / ("constraints-" + uuid.uuid4().hex + ".txt")
            try:
                packages = {}
                for dist in importlib.metadata.distributions():
                    package = dist.metadata.get("Name")
                    if package and normalized(package) not in CATALOG:
                        packages.setdefault(normalized(package), dist.version)
                constraints.write_text(
                    "".join(f"{package}=={version}\n" for package, version in packages.items()),
                    encoding="utf-8",
                )
                if update_version is not None:
                    if state["site"] and not versions:
                        versions = {
                            normalized(dist.metadata["Name"]): dist.version
                            for dist in importlib.metadata.distributions(path=[str(root / state["site"])])
                            if dist.metadata.get("Name")
                        }
                    for plugin in selected:
                        if plugin != name and plugin not in versions:
                            raise RuntimeError(f"Installed version of {plugin} is missing; update aborted")
                    try:
                        selected = [
                            f"{plugin}=={requested if plugin == name else Version(versions[plugin])}"
                            for plugin in selected
                        ]
                    except InvalidVersion as error:
                        raise RuntimeError("Invalid installed plugin version; update aborted") from error
                with child_lock_options(lock) as options:
                    subprocess.run(
                        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                         "--target", str(target), "--constraint", str(constraints), *selected],
                        check=True, capture_output=True, text=True, **options,
                    )
            except subprocess.CalledProcessError as error:
                shutil.rmtree(target, ignore_errors=True)
                raise RuntimeError(f"Plugin installation failed:\n{error.stderr or error.stdout}") from error
            finally:
                constraints.unlink(missing_ok=True)
            state["site"] = site
        elif name in CATALOG and not selected:
            state["site"] = None
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=root, prefix=".state-", delete=False
        ) as file:
            temporary = Path(file.name)
            try:
                json.dump(state, file, sort_keys=True)
                file.flush()
                os.fsync(file.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            if prepare:
                prepare(temporary, lock)
            if progress:
                progress("save")
            os.replace(temporary, root / "state.json")
        finally:
            temporary.unlink(missing_ok=True)
        return state


def configure(apps):
    """Apply published or candidate state before settings that depend on managed apps."""
    global configured_state
    candidate = os.environ.get("G3W_PLUGINS_CANDIDATE")
    if candidate:
        candidate = Path(candidate).resolve()
        if candidate.parent != directory() or not candidate.name.startswith(".state-"):
            raise RuntimeError("Invalid plugin preparation state")
        if not candidate.is_file():
            raise RuntimeError("Plugin preparation state is missing")
    state = read_state(candidate)
    if state["site"]:
        site = directory() / state["site"]
        if not site.is_dir():
            raise RuntimeError(f"Plugin installation is missing: {site}")
        base = {}
        for dist in importlib.metadata.distributions():
            name = dist.metadata.get("Name")
            if name:
                base.setdefault(normalized(name), dist.version)
        for dist in importlib.metadata.distributions(path=[str(site)]):
            name = dist.metadata.get("Name")
            if name:
                package = normalized(name)
                if package not in CATALOG and package in base and base[package] != dist.version:
                    raise RuntimeError(
                        f"Plugin dependency {package}=={dist.version} conflicts with "
                        f"the installed version {base[package]}; reinstall the managed plugins"
                    )
        for package, enabled in state["plugins"].items():
            if enabled and package in CATALOG:
                app = CATALOG[package]
                spec = importlib.machinery.PathFinder.find_spec(app, [str(site)])
                if spec is not None and spec.origin is None:
                    spec = importlib.machinery.PathFinder.find_spec(app, [str(site), *sys.path])
                if not spec_in_directory(spec, site.resolve()):
                    raise RuntimeError(
                        f"Managed plugin {package} is missing from or resolves outside {site}; reinstall it"
                    )
                if app in sys.modules and not spec_in_directory(
                    getattr(sys.modules[app], "__spec__", None), site.resolve()
                ):
                    raise RuntimeError(
                        f"Managed plugin {package} was already loaded outside {site}; restart the process"
                    )
        site_path = str(site)
        sys.path[:] = [entry for entry in sys.path if entry != site_path]
        sys.path.insert(0, site_path)
    for package, enabled in state["plugins"].items():
        app = MANAGED[package]
        if not enabled or package in CATALOG:
            apps[:] = [item for item in apps if item != app]
        if enabled and app not in apps:
            apps.append(app)
    apps[:] = [app for app in apps if app != "g3w_plugins"]
    if "g3w_plugins" not in apps:
        apps.append("g3w_plugins")
    configured_state = state

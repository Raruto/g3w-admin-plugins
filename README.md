# G3W-ADMIN-PLUGINS

[![PyPI version](https://img.shields.io/pypi/v/g3w-admin-plugins)](https://pypi.org/project/g3w-admin-plugins/)

Manage public G3W-ADMIN plugins and bundled modules from a superuser page or the
command line. External packages are installed only when enabled. The PyPI badge
will show a version after the first publication.

> Installing plugins and their dependencies executes third-party code. Restrict
> access to trusted superusers, review packages and back up the state directory
> and database before changing plugins.

## Installation

Install this repository in the Python environment used by G3W-ADMIN:

```sh
python -m pip install /path/to/g3w-admin-plugins
```

Set `G3W_PLUGINS_DIR` to a persistent, writable directory shared by the web and
consumer processes. In `base/settings/local_settings.py`, immediately after
defining `G3WADMIN_LOCAL_MORE_APPS` and before plugin-dependent settings, add:

```python
from g3w_plugins.manager import configure
configure(G3WADMIN_LOCAL_MORE_APPS)
```

Restart G3W-ADMIN and register the menu:

```sh
python manage.py sitetree_resync_apps g3w_plugins
```

Open **Plugin** in the sidebar as a superuser. The URL is `/admin/plugins/` when
a frontend is enabled, otherwise `/plugins/`; include any configured language prefix.

### Docker

Published G3W Docker settings and entrypoint do not install or configure this
manager automatically. Install it in both web and consumer containers and
configure it as above. In Docker, the default state directory is
`/shared-volume/.g3w_plugins`.

## Usage

```sh
python manage.py plugins list
python manage.py plugins enable g3w-admin-panoramax
python manage.py plugins disable g3w-admin-panoramax
```

| Topic | Behaviour |
|---|---|
| Catalog | Seven explicitly listed PyPI plugins; new packages require a catalog change. |
| Bundled modules | `editing`, `filemanager`, `qplotly` and `qtimeseries` are controlled here but updated with G3W-SUITE, not PyPI. Disabling them retains their data. If `qes` is installed, disable it before disabling `editing`. |
| Existing configuration | Unmanaged apps remain unchanged. Once managed, their saved desired state overrides the original setting. |
| Preparation | Enable, disable and update run migrations, collect static files and resynchronize menus before saving the desired state. Plugin-specific settings, external services and version compatibility remain your responsibility. |
| Restart | CLI changes require restarting web and consumer processes. The UI can request automatic reload on supported Docker deployments; otherwise restart manually. |
| Updates | The UI checks PyPI and offers newer stable versions for enabled external plugins. A displayed release may still be incompatible; checks and installation require network access. |
| Disable | Does not uninstall packages, reverse migrations or delete data. |

If portal is the configured frontend, change `FRONTEND` before disabling it.
Published Docker settings include portal by default. After upgrading from the
former `plugins` app, restart web and consumer processes and run
`python manage.py sitetree_resync_apps g3w_plugins` to refresh the sidebar.

For the state lifecycle, recovery, reload restrictions and deployment details, see
[plugin internals](g3w_plugins/README.md). For CLI output and behavior, see
[management commands](g3w_plugins/management/README.md).

## Development and releases

See [BDD tests](g3w_plugins/tests/README.md) for local, browser and Docker runs.
CI reuses the shared G3W plugin checks and runs Docker scenarios against the
published development image and upstream Docker settings.

After a successful push, CD uses the shared release actions to publish to PyPI and
create a GitHub release. Configure PyPI Trusted Publishing for
`raruto/g3w-admin-plugins` and `.github/workflows/cd.yml`, and allow GitHub
Actions to write repository contents. The CD workflow must exist on the default
branch. The shared release action publishes from any pushed branch and starts at
`v0.0.1` if there are no version tags; package versions are derived from Git tags.

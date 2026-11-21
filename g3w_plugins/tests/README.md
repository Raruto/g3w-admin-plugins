# BDD tests

The suite uses Behave feature files and Python step implementations:

| Feature | Coverage |
|---|---|
| [`access.feature`](features/access.feature) | Superuser access, CSRF and action validation |
| [`catalog.feature`](features/catalog.feature) | Catalog configuration and installation failure |
| [`manager.feature`](features/manager.feature) | State, installation, updates, locks and bundled modules |
| [`bootstrap.feature`](features/bootstrap.feature) | Automatic G3W settings integration and candidate state |
| [`jobs.feature`](features/jobs.feature) | Background jobs, progress and error handling |
| [`reload.feature`](features/reload.feature) | Preparation, reload coordination and consumer readiness |
| [`web.feature`](features/web.feature) | Page, sidebar, status and PyPI version checks |
| [`status.feature`](features/status.feature) | Browser status, controls and reload messages |
| [`docker.feature`](features/docker.feature) | Published Docker settings and management commands |

[`steps/`](steps/) contains the corresponding Python implementations. Backend
scenarios use isolated temporary state and mocks where appropriate. Browser scenarios
run the page's actual script with Playwright and a local HTTP server; the
server-confirmed reload scenario simulates the navigation type.

## Local runs

From the repository root, install test dependencies and a browser:

```sh
python -m pip install -e . -r requirements_test.txt huey==3.0.0
python -m playwright install chromium
python -m behave g3w_plugins/tests --tags="not @browser"
python -m behave g3w_plugins/tests/features --tags=browser -D browser=chromium
```

The browser parameter also accepts `firefox` and `webkit` after installing the
corresponding Playwright browser. Some reload scenarios require POSIX signals or
Linux pidfds and are skipped on unsupported platforms.

## Docker scenarios

`@docker` scenarios skip unless `G3W_PLUGINS_TEST_CONTAINER=1` is set inside a
**disposable** container. They require a published G3W-ADMIN image with
`/code/g3w-admin`, published G3W-SUITE Docker settings at
`/tmp/docker-settings.py`, and disposable PostGIS and Redis services. They
temporarily replace the container's local settings, run migrations and install
Panoramax from PyPI. Never point them at production data.

The tests use the unmodified upstream settings and the installed startup hook.
The command scenario starts with portal disabled and
does not validate the portal frontend. See
[`ci.yml`](../../.github/workflows/ci.yml) for the disposable CI setup.

```sh
python -m behave g3w_plugins/tests --tags=@docker
```

CI runs the shared G3W backend and browser jobs and a separate Docker job.
The package excludes these tests from the distribution.

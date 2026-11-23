# G3W-ADMIN-PLUGINS

[![PyPI version](https://img.shields.io/pypi/v/g3w-admin-plugins)](https://pypi.org/project/g3w-admin-plugins/)

Manage G3W-SUITE plugins from the web interface or command line. External
plugins are installed from PyPI when enabled.

![g3w-admin-plugins](https://github.com/user-attachments/assets/dd456d82-7c61-42ef-a55b-6759d7710aac)


## How to use

Install it from PyPI:

```sh
pip install g3w-admin-plugins
```

No further configuration is required. The manager activates automatically when G3W-SUITE starts.

Plugins are stored in `~/.g3w_plugins` or within `/shared-volume/.g3w_plugins` when running it Docker

### Uninstall

```sh
pip uninstall g3w-admin-plugins
```

An then restart containers. `.g3w_plugins` folders are retained.

### CLI

```sh
python manage.py plugins list
python manage.py plugins enable g3w-admin-panoramax
python manage.py plugins disable g3w-admin-panoramax
```

See [management commands](g3w_plugins/management/README.md) for further details.

## CI/CD

- [ci.yml](.github/workflows/ci.yml) runs checks and Docker tests.
- [cd.yml](.github/workflows/cd.yml) publishes to PyPI and creates a GitHub release.
- [tests](g3w_plugins/tests/README.md) folder holds BDD specs for docker and standalone tests.

---

**Compatibile with:**
[![g3w-admin version](https://img.shields.io/badge/g3w--admin-4.0-1EB300.svg?style=flat)](https://github.com/g3w-suite/g3w-admin/tree/v.4.0.x)
[![g3w-suite-docker version](https://img.shields.io/badge/g3w--suite--docker-4.0-1EB300.svg?style=flat)](https://github.com/g3w-suite/g3w-suite-docker/tree/v4.0.x)

---


**License:** MPL-2

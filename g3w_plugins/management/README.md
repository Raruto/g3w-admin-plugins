# Management command

[`commands/plugins.py`](commands/plugins.py) registers `manage.py plugins` in a
configured G3W-ADMIN installation. Run it from the G3W-ADMIN directory with the
same persistent `G3W_PLUGINS_DIR` used by the web and consumer processes.

| Command | Effect |
|---|---|
| `python manage.py plugins list` | Show running and desired state for each managed plugin |
| `python manage.py plugins enable g3w-admin-panoramax` | Install if needed, prepare and save the desired state |
| `python manage.py plugins disable g3w-admin-panoramax` | Prepare and save the disabled state |

`running` reflects the configuration loaded by this command's Django process.
`after_restart` is the saved decision; `None` means the plugin has not been
explicitly managed. Package and bundled-module names are listed by the command.

Enable and disable are synchronous: they run migrations, collect static files and
resynchronize menus against a candidate configuration before publishing it. Restart
the web and consumer processes to load the saved state. There is no CLI `update`
action; the web UI offers updates for enabled PyPI plugins.

Errors are reported as Django command errors. Preparation is not a database
transaction: failures can leave database, static or menu changes even when the
desired state was not saved. See [plugin internals](../README.md) for locking,
recovery and package-directory retention.

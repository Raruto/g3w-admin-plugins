import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

from g3w_plugins import manager


@then("a catalogued plugin is accepted")
def catalogued_plugin(context):
    manager.validate_change("g3w-admin-panoramax", True)


@then("an unknown plugin is rejected")
def unknown_plugin(context):
    try:
        manager.validate_change("unknown-plugin", True)
    except ValueError:
        return
    raise AssertionError("An unknown plugin was accepted")


@given("the plugin manager has enabled panoramax")
def enabled_plugin(context):
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    environment = patch.dict("os.environ", {"G3W_PLUGINS_DIR": directory.name})
    environment.start()
    context.add_cleanup(environment.stop)

    def install(command, **kwargs):
        Path(command[command.index("--target") + 1]).mkdir()

    with patch.object(manager.subprocess, "run", side_effect=install):
        manager.change("g3w-admin-panoramax", True)
    context.previous_state = manager.read_state()
    assert context.previous_state["plugins"]["g3w-admin-panoramax"]


@when("installing pdnd fails due to a dependency conflict")
def failed_installation(context):
    failure = subprocess.CalledProcessError(1, "pip", stderr="dependency conflict")
    with patch.object(manager.subprocess, "run", side_effect=failure):
        try:
            manager.change("g3w-admin-pdnd", True)
        except RuntimeError as error:
            context.install_error = str(error)
        else:
            raise AssertionError("Installation unexpectedly succeeded")


@then("the dependency conflict is reported")
def conflict_reported(context):
    assert "dependency conflict" in context.install_error


@then("the previous plugin configuration is preserved")
def configuration_preserved(context):
    assert manager.read_state() == context.previous_state

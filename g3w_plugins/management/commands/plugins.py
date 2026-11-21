from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from g3w_plugins.manager import MANAGED, change, read_state
from g3w_plugins.reload import prepare


class Command(BaseCommand):
    help = "List, enable or disable G3W modules and plugins"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("list", "enable", "disable"))
        parser.add_argument("plugin", nargs="?", choices=MANAGED)

    def handle(self, *args, **options):
        action = options["action"]
        plugin = options["plugin"]
        if action == "list":
            if plugin:
                raise CommandError("Do not specify a plugin with list")
            state = read_state()["plugins"]
            for package, app in MANAGED.items():
                running = app in settings.G3WADMIN_LOCAL_MORE_APPS
                desired = state.get(package)
                self.stdout.write(f"{package}: running={running}, after_restart={desired}")
            return
        if not plugin:
            raise CommandError("Specify a plugin")
        try:
            change(plugin, action == "enable", prepare=prepare)
        except (ValueError, RuntimeError, OSError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write("Saved and prepared. Restart G3W-SUITE and its consumer to apply the change.")

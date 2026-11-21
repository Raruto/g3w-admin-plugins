import os
import sys

from django.apps import AppConfig


def filter_plugin_menu(tree_items, context):
    request = context.get("request") if context else None
    user = getattr(request, "user", None)
    if user and user.is_active and user.is_superuser:
        return tree_items
    return [item for item in tree_items if item.url != "g3w-plugins"]


class PluginsConfig(AppConfig):
    name = "g3w_plugins"
    verbose_name = "G3W Plugins"

    def ready(self):
        from sitetree import sitetreeapp

        previous = sitetreeapp._ITEMS_PROCESSOR
        if not getattr(previous, "_g3w_plugins_filter", False):
            previous_args = sitetreeapp._ITEMS_PROCESSOR_ARGS_LEN

            def filter_items(tree_items, tree_sender, context):
                if previous:
                    if previous_args == 2:
                        tree_items = previous(tree_items=tree_items, tree_sender=tree_sender)
                    else:
                        tree_items = previous(tree_items=tree_items, tree_sender=tree_sender, context=context)
                return filter_plugin_menu(tree_items, context)

            filter_items._g3w_plugins_filter = True
            sitetreeapp.register_items_hook(filter_items)

        if os.environ.get("G3WSUITE_CONSUMER") == "0" and "run_huey" in sys.argv:
            from .reload import start_consumer_watcher
            start_consumer_watcher()

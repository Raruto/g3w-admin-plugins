"""Apply the manager state while G3W's local settings are being loaded."""

import importlib.machinery
import sys


class SettingsLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        import ast

        source = self.get_data(self.path)
        tree = ast.parse(source, filename=self.path)
        for index, node in enumerate(tree.body):
            targets = node.targets if isinstance(node, ast.Assign) else (
                [node.target] if isinstance(node, ast.AnnAssign) and node.value is not None else []
            )
            if any(isinstance(target, ast.Name) and target.id == "G3WADMIN_LOCAL_MORE_APPS"
                   for target in targets):
                hook = ast.parse(
                    "from g3w_plugins.manager import configure as _g3w_plugins_configure\n"
                    "_g3w_plugins_configure(G3WADMIN_LOCAL_MORE_APPS)\n"
                ).body
                for statement in hook:
                    ast.copy_location(statement, node)
                tree.body[index + 1:index + 1] = hook
                ast.fix_missing_locations(tree)
                break
        return compile(tree, self.path, "exec", dont_inherit=True, optimize=sys.flags.optimize)

    def exec_module(self, module):
        super().exec_module(module)
        apps = getattr(module, "G3WADMIN_LOCAL_MORE_APPS", None)
        if not isinstance(apps, list) or "g3w_plugins" not in apps:
            if "_g3w_plugins_configure" in vars(module):
                raise RuntimeError("G3W settings removed the configured plugin manager")
            raise RuntimeError(
                "The plugin manager could not configure G3W settings. "
                "Define G3WADMIN_LOCAL_MORE_APPS in a top-level assignment "
                "or call g3w_plugins.manager.configure() explicitly."
            )

        from . import manager

        if manager.configured_state is None:
            raise RuntimeError(
                "The plugin manager could not configure G3W settings. "
                "Define G3WADMIN_LOCAL_MORE_APPS in a top-level assignment "
                "or call g3w_plugins.manager.configure() explicitly."
            )
        first = apps.index("g3w_plugins")
        apps[:] = [app for index, app in enumerate(apps) if app != "g3w_plugins" or index == first]
        for package, enabled in manager.configured_state["plugins"].items():
            if (manager.MANAGED[package] in apps) != enabled:
                raise RuntimeError(f"G3W settings overwrote the configured state of {package}")


class SettingsFinder:
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "base.settings.local_settings":
            return None
        parent = sys.modules.get("base.settings")
        if parent is None or not all(
            hasattr(parent, name) for name in ("G3WADMIN_APPS", "G3WADMIN_PROJECT_APPS_BASE")
        ):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is not None:
            if type(spec.loader) is not importlib.machinery.SourceFileLoader:
                raise RuntimeError("The plugin manager requires source-based G3W local settings")
            spec.loader = SettingsLoader(fullname, spec.loader.path)
        return spec


def install():
    if any(isinstance(finder, SettingsFinder) for finder in sys.meta_path):
        return
    index = sys.meta_path.index(importlib.machinery.PathFinder)
    sys.meta_path.insert(index, SettingsFinder())

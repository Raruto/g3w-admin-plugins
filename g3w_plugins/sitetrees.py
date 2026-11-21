from sitetree.utils import item
from core.utils.tree import G3Wtree


sitetrees = (
    G3Wtree(
        "plugins",
        title="Plugin",
        module="g3w_plugins",
        items=[item("Plugin", "g3w-plugins", url_as_pattern=True,
                    icon_css_class="fa fa-puzzle-piece", access_by_perms=["auth.change_user"])],
    ),
    G3Wtree(
        "plugins_en",
        title="Plugins",
        module="g3w_plugins",
        items=[item("Plugin", "g3w-plugins", url_as_pattern=True,
                    icon_css_class="fa fa-puzzle-piece", access_by_perms=["auth.change_user"])],
    ),
)

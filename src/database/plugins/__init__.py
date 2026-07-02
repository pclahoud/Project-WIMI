"""WIMI Database Plugin Registry.

Plugins can register additional database mixins and schema migrations
that get composed into the UserDatabase class at startup.
"""

from .base import DatabasePlugin

# Global plugin registry
_plugins: dict = {}


def register_plugin(plugin: DatabasePlugin) -> None:
    """Register a database plugin.

    Args:
        plugin: A DatabasePlugin instance with a unique plugin_id
    """
    if plugin.plugin_id in _plugins:
        raise ValueError(f"Plugin '{plugin.plugin_id}' is already registered")
    _plugins[plugin.plugin_id] = plugin


def get_plugin(plugin_id: str) -> DatabasePlugin:
    """Get a registered plugin by ID."""
    if plugin_id not in _plugins:
        raise KeyError(f"Plugin '{plugin_id}' is not registered")
    return _plugins[plugin_id]


def get_all_plugins() -> dict:
    """Get all registered plugins."""
    return dict(_plugins)


def unregister_plugin(plugin_id: str) -> None:
    """Unregister a plugin by ID."""
    _plugins.pop(plugin_id, None)


__all__ = [
    'DatabasePlugin',
    'register_plugin',
    'get_plugin',
    'get_all_plugins',
    'unregister_plugin',
]

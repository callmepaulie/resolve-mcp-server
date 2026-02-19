"""
DaVinci Resolve connection management.

Handles importing the Resolve scripting module, connecting to the running
Resolve instance, and providing helper accessors used by all tool modules.
"""

import os
import sys

# Add Resolve scripting modules to Python path
_modules_path = os.environ.get(
    "PYTHONPATH_RESOLVE",
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/"
)
if _modules_path not in sys.path:
    sys.path.insert(0, _modules_path)

_resolve = None


def _connect():
    """Attempt to import DaVinciResolveScript and connect to running Resolve."""
    global _resolve
    try:
        import DaVinciResolveScript as dvr
        _resolve = dvr.scriptapp("Resolve")
    except ImportError:
        _resolve = None
    except Exception:
        _resolve = None


def get_resolve():
    """Get the Resolve application object. Raises if not available."""
    global _resolve
    if _resolve is None:
        _connect()
    if _resolve is None:
        raise RuntimeError(
            "Cannot connect to DaVinci Resolve. "
            "Make sure Resolve is running and scripting is enabled in Preferences > General."
        )
    return _resolve


def is_connected() -> bool:
    """Check if we can reach a running Resolve instance."""
    global _resolve
    if _resolve is None:
        _connect()
    if _resolve is None:
        return False
    try:
        _resolve.GetProductName()
        return True
    except Exception:
        _resolve = None
        return False


def get_project_manager():
    """Get the ProjectManager object."""
    return get_resolve().GetProjectManager()


def get_project():
    """Get the currently loaded project. Raises if none is open."""
    pm = get_project_manager()
    project = pm.GetCurrentProject()
    if project is None:
        raise RuntimeError("No project is currently open in DaVinci Resolve.")
    return project


def get_timeline():
    """Get the current timeline. Raises if none is selected."""
    project = get_project()
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("No timeline is currently selected. Open or create a timeline first.")
    return timeline


def get_media_pool():
    """Get the MediaPool object for the current project."""
    return get_project().GetMediaPool()


def get_media_storage():
    """Get the MediaStorage object."""
    return get_resolve().GetMediaStorage()


def reconnect():
    """Force a fresh connection attempt to Resolve."""
    global _resolve
    _resolve = None
    _connect()
    return is_connected()

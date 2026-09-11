# Browser coverage is split into non-discovered helper modules so Round 1 and
# the long-lived Manufacturer portal journey can evolve independently while
# preserving this module's historical pytest node IDs and helper imports.
from .manufacturer_portal_browser_core import *  # noqa: F401,F403
from .manufacturer_portal_browser_round1 import *  # noqa: F401,F403

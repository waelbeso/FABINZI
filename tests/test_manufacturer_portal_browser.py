# Browser coverage is split into non-discovered helper modules so Round 1 and
# the long-lived Manufacturer portal journey can evolve independently while
# preserving this module's historical pytest node IDs and helper imports.
from .manufacturer_portal_browser_core import (
    ARTIFACT_DIR,
    EXPECTED_SCREENSHOTS,
    _chrome,
    _clear_artifacts,
    _click,
    _click_element,
    _form_with_hidden,
    _login,
    _no_overflow,
    _replace,
    _shot,
    _wait,
    test_manufacturer_portal_real_chrome_a_to_h,
)
from .manufacturer_portal_browser_round1 import test_manufacturer_round1_real_chrome

__all__ = [
    "ARTIFACT_DIR",
    "EXPECTED_SCREENSHOTS",
    "_chrome",
    "_clear_artifacts",
    "_click",
    "_click_element",
    "_form_with_hidden",
    "_login",
    "_no_overflow",
    "_replace",
    "_shot",
    "_wait",
    "test_manufacturer_portal_real_chrome_a_to_h",
    "test_manufacturer_round1_real_chrome",
]

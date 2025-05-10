from __future__ import annotations

import logging
from importlib import metadata as _md

# ---------------------------------------------------------------------------
# package metadata
# ---------------------------------------------------------------------------
try:
    __version__: str = _md.version(__name__)
except _md.PackageNotFoundError:        # running from source tree
    __version__ = "0.0.0-dev"

# ---------------------------------------------------------------------------
# logging (modules get: log = logging.getLogger(__name__))
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
log = logging.getLogger(__name__)
log.debug("Package App initialised (v%s)", __version__)

# ---------------------------------------------------------------------------
# public re-exports – so callers can do `from App import CustomerDB`
# ---------------------------------------------------------------------------
from .Backend.Public_db  import PublicDatabaseService
from .Backend.User_db    import CustomerDB, BookingAgentDB, AirlineStaffDB

__all__: list[str] = [
    "PublicDatabaseService",
    "CustomerDB",
    "BookingAgentDB",
    "AirlineStaffDB",
    "__version__",
]

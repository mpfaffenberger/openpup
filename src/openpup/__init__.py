"""OpenPup: an always-on AI companion built on the code-puppy SDK.

Combines:
  * code-puppy as the underlying agent (used as a library/SDK),
  * puppy_kennel for persistent local memory,
  * a consciousness heartbeat (reflection, outreach, routines, inbound polling),
  * messaging integrations (Discord, Telegram, WhatsApp, Email, SMS).
"""

__version__ = "0.1.0"

from openpup.runtime import OpenPup

__all__ = ["OpenPup", "__version__"]

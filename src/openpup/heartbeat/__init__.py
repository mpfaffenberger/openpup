"""The OpenPup consciousness heartbeat.

A single async loop ticks on a jittered interval and runs the enabled
behaviors: idle self-reflection, proactive outreach, scheduled routines, and
inbound polling. State persists to the kennel + the OpenPup state dir so the
"mind" survives restarts.
"""

from openpup.heartbeat.engine import Heartbeat

__all__ = ["Heartbeat"]

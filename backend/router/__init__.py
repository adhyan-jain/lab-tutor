"""LLM-driven conversational routing, layered in front of the deterministic
QA/Socratic/diagnostic dispatch in `backend.api.chat_routes`.

See `router.py`'s module docstring for the authority boundary: this
package decides *routing* only, and any failure falls back to the
pre-existing deterministic dispatch unchanged.
"""

from backend.router.router import route_message
from backend.router.schema import RouterDecision, RouterMode

__all__ = ["RouterDecision", "RouterMode", "route_message"]

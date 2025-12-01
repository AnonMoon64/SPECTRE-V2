"""Simple message router for SPECTRE plugins.

Builds a mapping of message `type` -> handler plugins based on each plugin's
`handled_types`. If a plugin has an empty `handled_types` list, it is treated
as a broadcast/listener and will receive all messages (backwards-compat).
"""
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


class Router:
    def __init__(self, plugins: List[object]):
        self.plugins = plugins
        self.routes = {}  # type -> [plugin, ...]
        self._build_routes()

    def _build_routes(self):
        routes = {}
        for plugin in self.plugins:
            types = getattr(plugin, 'handled_types', []) or []
            if not types:
                # empty handled_types means "listen to everything"
                routes.setdefault('_broadcast', []).append(plugin)
            else:
                for t in types:
                    routes.setdefault(t, []).append(plugin)
        self.routes = routes
        logger.info(f"Router built routes: { {k: [p.name for p in v] for k,v in routes.items()} }")

    def dispatch(self, message: dict):
        """Dispatch a message to all matching plugins.

        message must be a dict containing a 'type' key.
        """
        t = message.get('type')
        if t is None:
            # If message has no type, treat as broadcast
            recipients = self.routes.get('_broadcast', [])
        else:
            recipients = list(self.routes.get(t, []))
            # include broadcast listeners
            recipients.extend(self.routes.get('_broadcast', []))

        # Debug: log recipients for this message type
        try:
            names = [getattr(p, 'name', str(p)) for p in recipients]
            logger.info(f"Dispatching message type='{t}' to plugins: {names}")
        except Exception:
            pass

        for plugin in recipients:
            try:
                plugin.handle_response(message)
            except Exception as e:
                logger.error(f"Error dispatching message to plugin {getattr(plugin,'name',str(plugin))}: {e}")

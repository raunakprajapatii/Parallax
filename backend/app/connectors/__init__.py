"""Credential-free demo connectors and the stable connector registry.

The connectors expose only the normalized models from ``app.agent.models`` to
the agent. Provider-specific clients can be added behind the same interface
without changing the retrieval or synthesis code.
"""

from .config import ConnectorConfig
from .registry import ConnectorRegistry

__all__ = ["ConnectorConfig", "ConnectorRegistry"]

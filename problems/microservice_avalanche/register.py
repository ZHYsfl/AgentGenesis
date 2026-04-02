"""Registration entry for Microservice Avalanche"""

from .config import MicroserviceAvalancheConfig


def register():
    """Register the phase configuration."""
    return MicroserviceAvalancheConfig()

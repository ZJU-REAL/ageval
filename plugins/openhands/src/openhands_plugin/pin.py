"""Pinned OpenHands SDK and tools wheels.

The Dockerfile bake and the on-demand install both read this pin.
A range is not a pin: setup installs these two distributions at this version
or fails closed.
"""

SDK_VERSION = "1.56.0"
SDK_DISTRIBUTIONS = ("openhands-sdk", "openhands-tools")


def requirement(version: str) -> tuple[str, ...]:
    """Exact ``name==version`` specs for the SDK and the tools package."""
    return tuple(f"{name}=={version}" for name in SDK_DISTRIBUTIONS)


__all__ = ["SDK_DISTRIBUTIONS", "SDK_VERSION", "requirement"]

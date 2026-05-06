"""DMX interface ABC.

The engine talks to one of:
  * `EnttecProInterface` — real serial output (Eurolite USB-DMX512 PRO MK2 etc.)
  * `NullInterface`      — in-memory, used when no hardware available or in tests
  * Any future driver (Art-Net, sACN, OLA…) that implements the same surface

The interface is intentionally minimal: we render a 512-byte universe and call
`send`. Reconnection, packet framing, and timing are all the driver's problem.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


UNIVERSE_SIZE = 512


class DmxInterface(ABC):
    """Synchronous interface — blocking I/O is fine, the DMX writer thread owns it."""

    @abstractmethod
    def open(self) -> None:
        """Open the underlying device. Idempotent."""

    @abstractmethod
    def close(self) -> None:
        """Close the underlying device. Idempotent."""

    @abstractmethod
    def send(self, universe: int, frame: bytes) -> None:
        """Send a 512-byte universe frame.

        `frame` MUST be exactly 512 bytes. Drivers should never raise on transient
        I/O errors — they reconnect internally and drop the frame if the device is
        gone (the next frame will succeed).
        """

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Whether the underlying device is currently open and usable."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable identifier for logging."""

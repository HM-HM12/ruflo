"""Abstract broker/exchange interface. PaperBroker (default) and any live
broker adapter both implement this so the Execution Engine is agnostic to
where orders actually go."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain import Fill, Order


class BrokerInterface(ABC):
    @abstractmethod
    async def submit_order(self, order: Order) -> Order:
        """Submit an order and return it with updated status/id."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Attempt to cancel a resting order. Returns True if cancelled."""

    @abstractmethod
    async def get_order_status(self, order_id: str) -> Order:
        """Poll the current status of a previously submitted order."""

    @abstractmethod
    async def get_fills(self, order_id: str) -> list[Fill]:
        """Return all fills (including partials) recorded for an order."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Connectivity check used by the reconnection handler."""

    @property
    @abstractmethod
    def is_live(self) -> bool:
        """True only for a broker that can move real money. Used as a
        belt-and-suspenders assertion at the top of the execution engine."""

from typing import Protocol

from event_gateway.schemas import EventRequest


class AccountApplicationError(Exception):
    pass


class AccountApplier(Protocol):
    def apply_event(self, event: EventRequest) -> None:
        pass


class NoopAccountApplier:
    def apply_event(self, event: EventRequest) -> None:
        return None

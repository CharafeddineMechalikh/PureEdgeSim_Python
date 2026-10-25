"""Discrete-event engine, the counterpart of the simulationengine package."""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(order=True)
class Event:
    time: float
    serial: int
    destination: "SimEntity" = field(compare=False)
    tag: int = field(compare=False, default=0)
    data: Any = field(compare=False, default=None)


class FutureQueue:
    def __init__(self) -> None:
        self._heap: list[Event] = []
        self._serial = 0

    def add(self, destination: "SimEntity", time: float, tag: int = 0, data: Any = None) -> Event:
        event = Event(time, self._serial, destination, tag, data)
        self._serial += 1
        heapq.heappush(self._heap, event)
        return event

    def pop(self) -> Event | None:
        return heapq.heappop(self._heap) if self._heap else None

    def remove(self, predicate: Callable[[Event], bool]) -> int:
        kept = [event for event in self._heap if not predicate(event)]
        removed = len(self._heap) - len(kept)
        if removed:
            self._heap = kept
            heapq.heapify(self._heap)
        return removed

    def __len__(self) -> int:
        return len(self._heap)


class SimEntity:
    def __init__(self, engine: "Engine") -> None:
        self.engine = engine
        engine.add_entity(self)

    @property
    def clock(self) -> float:
        return self.engine.clock

    def schedule(self, destination: "SimEntity", delay: float, tag: int = 0, data: Any = None) -> Event:
        return self.engine.schedule(destination, delay, tag, data)

    def schedule_now(self, destination: "SimEntity", tag: int = 0, data: Any = None) -> Event:
        return self.schedule(destination, 0.0, tag, data)

    def process_event(self, event: Event) -> None:
        raise NotImplementedError

    def on_simulation_start(self) -> None:
        pass

    def on_simulation_end(self) -> None:
        pass


class Engine:
    """Time-ordered event queue with deterministic tie breaking by insertion serial."""

    def __init__(self, duration: float) -> None:
        self.duration = float(duration)
        self.clock = 0.0
        self.queue = FutureQueue()
        self.entities: list[SimEntity] = []
        self.running = False

    def add_entity(self, entity: SimEntity) -> None:
        self.entities.append(entity)

    def schedule(self, destination: SimEntity, delay: float, tag: int = 0, data: Any = None) -> Event:
        return self.queue.add(destination, self.clock + max(0.0, delay), tag, data)

    def clock_in_minutes(self) -> float:
        return self.clock / 60.0

    def terminate(self) -> None:
        self.running = False

    def start(self) -> None:
        self.clock = 0.0
        self.running = True
        for entity in list(self.entities):
            entity.on_simulation_start()
        while self.running:
            event = self.queue.pop()
            if event is None:
                break
            self.clock = event.time
            event.destination.process_event(event)
        self.running = False
        for entity in list(self.entities):
            entity.on_simulation_end()

"""The discrete-event engine: ordering, clock, termination and removal."""
from __future__ import annotations

from pureedgesim import Engine, EventType, SimEntity


class Recorder(SimEntity):
    def __init__(self, engine, label="a"):
        super().__init__(engine)
        self.label = label
        self.seen = []

    def process_event(self, event):
        self.seen.append((self.clock, event.tag, event.data))


def test_events_run_in_time_order():
    engine = Engine(10)
    entity = Recorder(engine)
    entity.schedule(entity, 5.0, EventType.SEND_TO_ORCH, "late")
    entity.schedule(entity, 1.0, EventType.SEND_TO_ORCH, "early")
    engine.start()
    assert [entry[2] for entry in entity.seen] == ["early", "late"]
    assert [entry[0] for entry in entity.seen] == [1.0, 5.0]


def test_same_time_keeps_insertion_order():
    engine = Engine(10)
    entity = Recorder(engine)
    for index in range(5):
        entity.schedule(entity, 2.0, EventType.SEND_TO_ORCH, index)
    engine.start()
    assert [entry[2] for entry in entity.seen] == [0, 1, 2, 3, 4]


def test_negative_delay_is_clamped_to_now():
    engine = Engine(10)
    entity = Recorder(engine)
    entity.schedule(entity, -3.0, EventType.SEND_TO_ORCH, "x")
    engine.start()
    assert entity.seen[0][0] == 0.0


def test_events_scheduled_during_processing_are_kept_ordered():
    class Reactor(Recorder):
        def process_event(self, event):
            super().process_event(event)
            if event.data == "first":
                self.schedule(self, 0.5, EventType.SEND_TO_ORCH, "nested")

    engine = Engine(10)
    entity = Reactor(engine)
    entity.schedule(entity, 1.0, EventType.SEND_TO_ORCH, "first")
    entity.schedule(entity, 2.0, EventType.SEND_TO_ORCH, "second")
    engine.start()
    assert [entry[2] for entry in entity.seen] == ["first", "nested", "second"]
    assert [entry[0] for entry in entity.seen] == [1.0, 1.5, 2.0]


def test_terminate_stops_the_loop_and_drops_pending_events():
    engine = Engine(100)
    entity = Recorder(engine)
    for index in range(10):
        entity.schedule(entity, index, EventType.SEND_TO_ORCH, index)

    class Stopper(Recorder):
        def process_event(self, event):
            super().process_event(event)
            self.engine.terminate()

    stopper = Stopper(engine, "stopper")
    stopper.schedule(stopper, 3.0, EventType.SEND_TO_ORCH, "halt")
    engine.start()
    assert stopper.seen == [(3.0, EventType.SEND_TO_ORCH, "halt")]
    assert [entry[0] for entry in entity.seen] == [0.0, 1.0, 2.0, 3.0]


def test_start_and_end_hooks_fire_once():
    class Hooked(Recorder):
        def __init__(self, engine):
            super().__init__(engine)
            self.starts = self.ends = 0

        def on_simulation_start(self):
            self.starts += 1
            self.schedule(self, 1.0, EventType.SEND_TO_ORCH, "x")

        def on_simulation_end(self):
            self.ends += 1

    engine = Engine(10)
    entity = Hooked(engine)
    engine.start()
    assert (entity.starts, entity.ends, len(entity.seen)) == (1, 1, 1)


def test_remove_predicate_drops_only_matching_events():
    engine = Engine(10)
    entity = Recorder(engine)
    entity.schedule(entity, 1.0, EventType.SEND_TO_ORCH, "keep")
    entity.schedule(entity, 2.0, EventType.SEND_TO_ORCH, "drop")
    removed = engine.queue.remove(lambda event: event.data == "drop")
    engine.start()
    assert removed == 1
    assert [entry[2] for entry in entity.seen] == ["keep"]


def test_clock_in_minutes():
    engine = Engine(10)
    entity = Recorder(engine)
    entity.schedule(entity, 120.0, EventType.SEND_TO_ORCH, "x")
    engine.start()
    assert entity.seen[0][0] == 120.0
    assert engine.clock_in_minutes() == 2.0

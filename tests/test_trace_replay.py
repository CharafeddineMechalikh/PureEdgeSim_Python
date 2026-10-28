"""The trace replay of ``examples/trace_replay``, checked on the committed trace.

The example makes four claims, and each is tested on the real thing: the generator
reads the shipped CSV through a real ``SimulationManager``, the shrunk scenario is
launched end to end, and the two knobs the README compares are driven through the
same code path the command line uses.

* Every one of the 8819 recorded invocations becomes one request of its own, at the
  second it was recorded, with its sizes, its length and its deadline derived from
  the two token counts of the trace.
* The recorded requests are handed to the fleet in turn, so the load stays even
  while the arrival process stays exactly as recorded.
* The replay draws nothing: two different seeds give the same task list, and a run
  that is shorter than the trace truncates the replay instead of failing it.
* A full launch of the scenario reproduces the numbers the README reports, and
  loosening the per-token budget moves the pass mark without touching the queue.
"""
from __future__ import annotations

from collections import Counter

import pytest

from examples.trace_replay import trace_replay as replay
from pureedgesim import (COLUMNS, Engine, Randomness, Scenario, SimulationManager, load_parameters,
                         load_settings)

# The committed settings replay the whole hour inside 3480 s, so this is the period
# the full-trace assertions run on.
TEN_MINUTES = 600.0
SEED = 42

# The first line of the trace: one request with 4808 prompt tokens and a completion
# of 10 tokens, mapped with the default values of the example.
FIRST_CONTEXT = 4808
FIRST_GENERATED = 10


def _build(duration: float | None = None, seed: int = SEED) -> SimulationManager:
    """A manager holding the replayed workload, built but not yet run."""
    parameters = load_parameters(replay.SETTINGS / "simulation_parameters.properties")
    if duration is not None:
        parameters.simulation_duration = duration
    parameters.random_seed = seed
    parameters.save_log_file = False
    files = load_settings(replay.SETTINGS)
    Randomness.set_seed(seed)
    Randomness.begin_scenario(0)
    manager = SimulationManager(Engine(parameters.simulation_duration), parameters, files,
                                Scenario(parameters.orchestration_architectures[0],
                                         parameters.orchestration_algorithms[0],
                                         parameters.max_number_of_devices),
                                custom_task_generator=replay.TraceTaskGenerator)
    manager.start_simulation()
    return manager


@pytest.fixture(scope="module")
def full_replay() -> SimulationManager:
    """The whole recorded hour, generated against the committed fleet."""
    return _build()


def test_the_settings_replay_the_trace_on_one_edge_server():
    parameters = load_parameters(replay.SETTINGS / "simulation_parameters.properties")
    assert parameters.orchestration_architectures == ["EDGE_ONLY"]
    assert parameters.simulation_duration == 3480.0, "the period has to cover the 3436 s of the recorded hour"
    assert parameters.min_number_of_devices == parameters.max_number_of_devices == 50


def test_every_recorded_invocation_becomes_one_request(full_replay):
    tasks = sorted(full_replay.tasks, key=lambda task: task.id)
    assert len(tasks) == 8819, "the committed trace holds 8819 recorded invocations"
    assert tasks[0].time == 1.0, "the first invocation lands after the initialization second"
    assert tasks[-1].time == 3437.0, "the last one arrives 3436 seconds after the first"
    assert all(task.request_task_count == 1 for task in tasks), "every recorded invocation is a request of its own"


def test_the_recorded_tokens_set_the_size_the_length_and_the_deadline(full_replay):
    first = min(full_replay.tasks, key=lambda task: task.id)
    assert first.request_size == FIRST_CONTEXT * 4 * 8, "4 bytes per prompt token, sent up"
    assert first.result_size == FIRST_GENERATED * 4 * 8, "4 bytes per completion token, sent back"
    assert first.length == FIRST_CONTEXT * 12 + FIRST_GENERATED * 2000, (
        "the prompt is read once, the completion is produced token by token")
    assert first.max_latency == pytest.approx(2 + FIRST_GENERATED * 0.1), "the budget grows with the completion"
    assert first.request_deadline == pytest.approx(1 + 2 + FIRST_GENERATED * 0.1), "and counts from the arrival"


def test_the_requests_are_handed_to_the_devices_in_turn(full_replay):
    tasks = sorted(full_replay.tasks, key=lambda task: task.id)
    sources = [task.source_device for task in tasks]
    assert len(set(sources[:50])) == 50, "the first fifty requests go to fifty different devices"
    assert sources[50] is sources[0], "then the round starts again on the first device"
    per_device = Counter(sources)
    assert len(per_device) == 50
    assert max(per_device.values()) - min(per_device.values()) <= 1, (
        "the fleet shares the recorded hour as evenly as 8819 requests allow")


def test_a_shorter_run_stops_the_replay_instead_of_failing_it():
    tasks = _build(duration=TEN_MINUTES).tasks
    assert len(tasks) == 1482, "the trace holds 1482 invocations during its first ten minutes"
    assert max(task.time for task in tasks) == 587.0, (
        "the last request replayed is the last one that arrives before the end of the run")


def test_the_replay_draws_no_random_value():
    with_seed_one = sorted((task.time, task.request_size, task.length) for task in _build(seed=1).tasks)
    with_seed_two = sorted((task.time, task.request_size, task.length) for task in _build(seed=2).tasks)
    assert with_seed_one == with_seed_two, "the same trace and the same fleet give the same task list"


def test_a_real_launch_replays_the_whole_hour_on_the_edge(tmp_path):
    row = replay.run(synthetic=False, output=tmp_path / "recorded")
    assert row[COLUMNS[0]] == "EDGE_ONLY"
    assert row[COLUMNS[7]] == 8819, "the whole recorded hour reaches the simulator"
    assert row[COLUMNS[17]] == 8819, "and none of it is executed on another tier"
    assert row[COLUMNS[8]] == 3180, "the bursts of the recorded traffic make 63.94 percent miss their deadline"
    assert row[COLUMNS[5]] == pytest.approx(120213.0921, abs=1e-4)


def test_the_synthetic_baseline_of_the_same_means_meets_every_deadline(tmp_path):
    row = replay.run(synthetic=True, output=tmp_path / "synthetic")
    assert row[COLUMNS[7]] == row[COLUMNS[8]], "poisson arrivals at the same mean never build a queue"
    assert row[COLUMNS[5]] < 500.0, "the whole run waits less than eight minutes of task time"


def test_the_mapping_knobs_reach_the_generator(tmp_path):
    default = replay.run(synthetic=False, output=tmp_path / "default")
    loosened = replay.run(synthetic=False, output=tmp_path / "loosened", decode_budget=0.5)
    assert loosened[COLUMNS[5]] == pytest.approx(default[COLUMNS[5]], abs=1e-4), (
        "the queue is the same: only the pass mark moved")
    assert loosened[COLUMNS[8]] == 5088, "against 3180 with the default per-token promise"


def test_an_unknown_option_is_rejected(capsys):
    with pytest.raises(ValueError, match="the tuning knobs are"):
        replay.main(["--nope=3"])

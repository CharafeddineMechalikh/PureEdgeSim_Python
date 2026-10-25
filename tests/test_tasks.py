"""Task generation: the per-minute burst, random arrivals, and the task accessors."""
from __future__ import annotations

import pytest

from conftest import build_manager
from pyedgesim import Task
from pyedgesim.distribution import ConstantDistribution, UniformDistribution
from pyedgesim.config import Application
from pyedgesim.nodes import NodeType
from pyedgesim.tasks import DefaultTaskGenerator, TaskStatus


def application(rate=10, usage=100, arrival=None, length=1000.0, latency=1e9):
    return Application(name="probe", type="probe", rate=ConstantDistribution(rate),
                       usage_percentage=usage, latency=ConstantDistribution(latency),
                       container_size=ConstantDistribution(8e6), request_size=ConstantDistribution(8e3),
                       results_size=ConstantDistribution(8e3), task_length=ConstantDistribution(length),
                       arrival_distribution=arrival)


@pytest.fixture
def gen(parameters, files):
    """A real manager whose application list has been replaced by the probe profiles."""
    engine, manager = build_manager(parameters, files, devices=10)
    return engine, manager


def generate(manager, *applications, duration=None):
    if duration is not None:
        manager.parameters.simulation_duration = duration
    manager.applications = list(applications)
    return DefaultTaskGenerator(manager).generate()


def test_a_task_starts_running_and_is_not_served_yet(gen):
    engine, manager = gen
    device = manager.edge_devices[0]
    task = Task(id=1, type="t", application_id=0, length=1.0, container_size=1.0, request_size=1.0,
                result_size=1.0, max_latency=1.0, time=0.0, source_device=device, registry=device)
    assert task.status == TaskStatus.RUNNING
    assert not task.is_served()
    assert task.get_orchestrator() is device
    assert device.is_orchestrator
    assert task.waiting_time == 0.0


def test_task_delays_add_network_waiting_and_execution(gen):
    engine, manager = gen
    device = manager.edge_devices[0]
    task = Task(id=1, type="t", application_id=0, length=1.0, container_size=1.0, request_size=1.0,
                result_size=1.0, max_latency=1.0, time=0.0, source_device=device, registry=device)
    task.arrival_time, task.execution_start_time, task.execution_finish_time = 5.0, 8.0, 12.0
    task.total_network_time = 1.5
    assert (task.waiting_time, task.actual_cpu_time, task.total_delay) == (3.0, 4.0, 8.5)
    assert task.total_delay == task.total_network_time + task.waiting_time + task.actual_cpu_time


def test_without_an_arrival_pattern_a_burst_lands_in_each_minute(gen):
    engine, manager = gen
    tasks = generate(manager, application(rate=4), duration=180.0)
    devices = [d for d in manager.edge_devices if d.generates_tasks]
    assert len(tasks) == 4 * 3 * len(devices)
    for device in devices:
        times = sorted(task.time for task in tasks if task.source_device is device)
        gaps = [later - earlier for earlier, later in zip(times, times[1:])]
        # The rate is 4 per minute, so each burst is spaced by 60 // 4 = 15 seconds;
        # the only larger gaps are the ones between two consecutive minutes.
        assert gaps.count(15) == 9
        assert all(0 < gap < 75 for gap in gaps)
        assert times[0] % 60 < 75


def test_a_zero_rate_application_produces_nothing(gen):
    engine, manager = gen
    assert generate(manager, application(rate=0), duration=120.0) == []


def test_a_shorter_simulation_than_a_minute_produces_nothing(gen):
    engine, manager = gen
    assert generate(manager, application(rate=20), duration=30.0) == []


def test_arrival_patterns_are_spread_over_the_whole_simulation(gen):
    engine, manager = gen
    tasks = generate(manager, application(rate=20, arrival=UniformDistribution(10, 20)), duration=120.0)
    assert tasks
    gaps = sorted({later.time - earlier.time
                   for earlier, later in zip(tasks, tasks[1:]) if earlier.source_device is later.source_device})
    assert all(gap >= 1.0 for gap in gaps)
    assert max(task.time for task in tasks) < 120.0
    # The device is not assumed busy at t=0: the first task lands after a random delay.
    assert min(task.time for task in tasks) > 0.0


def test_arrival_gaps_below_a_second_are_clamped(gen):
    engine, manager = gen
    devices = [d for d in manager.edge_devices if d.generates_tasks]
    tasks = generate(manager, application(arrival=ConstantDistribution(0.2)), duration=10.0)
    for device in devices:
        times = sorted(task.time for task in tasks if task.source_device is device)
        # A gap below one second would keep the loop busy without moving, so the
        # sampled 0.2 s is clamped to 1 s and each task lands on a whole second.
        assert [t - earlier for earlier, t in zip(times, times[1:])] == [1] * (len(times) - 1)
        assert times[-1] < 10.0


def test_generated_tasks_are_ordered_by_arrival_time(gen):
    engine, manager = gen
    tasks = generate(manager, application(rate=6), duration=120.0)
    assert tasks == sorted(tasks, key=lambda task: task.time)


def test_ids_are_unique_and_start_at_one(gen):
    engine, manager = gen
    tasks = generate(manager, application(rate=3), duration=120.0)
    # Generation is sequential but the list is re-ordered by arrival time, so the
    # ids are a permutation of 1..N rather than a ramp.
    assert sorted(task.id for task in tasks) == list(range(1, len(tasks) + 1))
    assert tasks[0].time == min(task.time for task in tasks)


def test_the_usage_percentage_splits_the_devices_and_the_last_app_gets_the_rest(gen):
    engine, manager = gen
    generating = [d for d in manager.edge_devices if d.generates_tasks]
    first, second = application(rate=1, usage=30), application(rate=1, usage=70)
    tasks = generate(manager, first, second, duration=60.0)
    by_app = {}
    for task in tasks:
        by_app.setdefault(task.application_id, set()).add(task.source_device)
    assert len(by_app[0]) == int(30 * len(generating) / 100)
    assert by_app[1] == set(generating) - by_app[0]


def test_devices_that_do_not_generate_tasks_get_nothing(gen):
    engine, manager = gen
    for device in manager.edge_devices:
        device.generates_tasks = False
    assert generate(manager, application(rate=5), duration=60.0) == []


def test_every_task_draws_its_own_sizes_from_the_distributions(gen):
    engine, manager = gen
    app = application(rate=20)
    app.request_size = UniformDistribution(1000, 2000)
    app.task_length = UniformDistribution(500, 600)
    tasks = generate(manager, app, duration=60.0)
    assert len({task.request_size for task in tasks}) > 1
    assert len({task.length for task in tasks}) > 1
    assert all(1000 <= task.request_size <= 2000 for task in tasks)


def test_tasks_carry_the_application_type_and_the_cloud_registry(gen):
    engine, manager = gen
    tasks = generate(manager, application(rate=2), duration=60.0)
    assert {task.type for task in tasks} == {"probe"}
    assert {task.registry for task in tasks} == {manager.registry}
    assert manager.registry.type == NodeType.CLOUD
    assert {task.source_device.type for task in tasks} == {NodeType.EDGE_DEVICE}

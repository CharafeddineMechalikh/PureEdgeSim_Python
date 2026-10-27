"""Simulation manager: the task lifecycle, the four failure phases and the metrics."""
from __future__ import annotations

import pytest

from conftest import build_manager, run_manager
from pureedgesim import LinkType, NodeStatus, NodeType, TaskStatus
from pureedgesim.network import NetworkLink


@pytest.fixture
def live(parameters, files):
    """A real simulation, run to the end: 20 devices, two minutes, all layers."""
    return run_manager(parameters, files, "ALL", "TRADE_OFF", devices=20)


def test_every_generated_task_ends_with_exactly_one_reason(live):
    engine, manager = live
    metrics = manager.metrics
    assert metrics.generated_tasks == len(manager.tasks) > 0
    assert (metrics.succeeded_tasks + metrics.delay_failures + metrics.death_failures
            + metrics.mobility_failures + metrics.not_executed
            + metrics.not_generated) == metrics.generated_tasks
    assert len(manager.finished_tasks) == metrics.generated_tasks
    assert all(task.failed or task.status == TaskStatus.SUCCESS for task in manager.tasks)


def test_the_engine_stops_past_the_duration_to_finish_the_workload(live):
    engine, manager = live
    assert engine.clock > manager.parameters.simulation_duration
    assert manager.parameters.wait_for_all_tasks
    assert engine.running is False


def test_execution_happened_on_the_layer_chosen_by_the_orchestrator(live):
    engine, manager = live
    metrics = manager.metrics
    assert metrics.cloud_tasks + metrics.edge_tasks + metrics.mist_tasks == metrics.generated_tasks
    assert metrics.succeeded_tasks == metrics.cloud_successes + metrics.edge_successes + metrics.mist_successes
    assert metrics.executed_tasks == metrics.generated_tasks
    assert metrics.cloud_tasks > 0 and metrics.edge_tasks > 0 and metrics.mist_tasks > 0


def test_the_measured_delay_is_the_sum_of_the_three_parts(live):
    engine, manager = live
    for task in manager.tasks[:50]:
        delay = task.total_network_time + task.waiting_time + task.actual_cpu_time
        assert task.total_delay == pytest.approx(delay)
        assert task.actual_cpu_time == pytest.approx(task.execution_duration)
        # A delay failure comes either from the subtask's own bound or from the
        # end-to-end deadline of its request, which may expire while it waits.
        if task.status == TaskStatus.FAILED_DUE_TO_DELAY:
            assert task.total_delay >= task.max_latency or task.request_deadline > 0
    assert manager.metrics.total_execution_time == pytest.approx(
        sum(task.actual_cpu_time for task in manager.tasks))
    assert manager.metrics.total_waiting_time == pytest.approx(
        sum(task.waiting_time for task in manager.tasks))


def test_a_dead_device_does_not_generate_its_task(parameters, files):
    engine, manager = build_manager(parameters, files, devices=10)
    task = manager.tasks[0]
    task.source_device.status = NodeStatus.DEAD
    before = manager.metrics.not_generated
    manager._send_to_orchestrator(task)
    assert task.status == TaskStatus.FAILED_DUE_TO_DEVICE_DEATH
    # The task was never offloaded, so it is counted as not generated rather
    # than as a failure.
    assert manager.metrics.not_generated == before + 1
    assert manager.metrics.death_failures == 0
    assert task.destination is None
    assert manager.metrics.executed_tasks == 0


def test_an_orchestrator_out_of_radio_range_fails_the_task(parameters, files):
    engine, manager = build_manager(parameters, files, devices=10)
    parameters.enable_orchestrators = True
    parameters.deploy_orchestrator = "MIST"
    task = manager.tasks[0]
    other = next(device for device in manager.edge_devices if device is not task.source_device)
    task.orchestrator = other
    manager.parameters.edge_devices_range = 0.0
    assert manager._send_from_orchestrator_to_destination(task) is None
    assert task.status == TaskStatus.FAILED_DUE_TO_DEVICE_MOBILITY
    assert manager.metrics.mobility_failures == 1


def test_a_destination_without_resources_is_refused(parameters, files):
    engine, manager = build_manager(parameters, files, devices=10)
    task = manager.tasks[0]
    task.destination = manager.nodes_generator.cloud_nodes[0]
    task.destination.available_ram = 0.0
    manager.task_failed(task, 2)
    assert task.status == TaskStatus.INSUFFICIENT_RESOURCES
    assert manager.metrics.not_executed == 1


def test_a_latency_breach_is_counted_when_the_results_come_back(parameters, files):
    engine, manager = build_manager(parameters, files, devices=10)
    task = manager.tasks[0]
    task.destination = manager.nodes_generator.cloud_nodes[0]
    task.max_latency = 0.0
    task.total_network_time = 1.0
    manager._results_returned(task)
    assert task.status == TaskStatus.FAILED_DUE_TO_DELAY
    assert manager.metrics.delay_failures == 1
    assert manager.metrics.succeeded_tasks == 0


def test_results_are_counted_only_once(parameters, files):
    engine, manager = build_manager(parameters, files, devices=10)
    task = manager.tasks[0]
    manager._results_returned(task)
    manager._results_returned(task)
    assert manager.metrics.succeeded_tasks == 1


def test_a_task_without_any_destination_is_not_executed(parameters, files):
    engine, manager = build_manager(parameters, files, "CLOUD_ONLY", devices=10)
    manager.orchestrator.candidates = []
    task = manager.tasks[0]
    manager._send_from_orchestrator_to_destination(task)
    assert task.status == TaskStatus.NO_OFFLOADING_DESTINATIONS
    assert manager.metrics.not_executed == 1
    assert manager.metrics.network_requests == 0


def test_the_mist_architecture_places_every_sent_task_on_a_device(parameters, files):
    engine, manager = run_manager(parameters, files, "MIST_ONLY", "TRADE_OFF", devices=20)
    metrics = manager.metrics
    assert metrics.edge_tasks == metrics.cloud_tasks == 0
    assert metrics.mist_tasks == manager.get_tasks_sent_number()
    assert all(task.destination.type == NodeType.EDGE_DEVICE
               for task in manager.tasks if task.destination is not None)
    # With a 10 m radio range and no cloud or edge layer, some devices have no
    # mist node nearby: their tasks are generated but never placed.
    assert metrics.mist_tasks < metrics.generated_tasks
    assert metrics.not_executed > 0
    assert metrics.death_failures == 0


def test_the_cloud_only_architecture_never_uses_the_edge(parameters, files):
    engine, manager = run_manager(parameters, files, "CLOUD_ONLY", "TRADE_OFF", devices=20)
    assert manager.metrics.mist_tasks == manager.metrics.edge_tasks == 0
    assert manager.metrics.cloud_tasks == manager.metrics.generated_tasks


def test_the_orchestrator_mode_selects_the_layer(parameters, files):
    for mode, expected in (("MIST", NodeType.EDGE_DEVICE), ("CLOUD", NodeType.CLOUD),
                           ("EDGE", NodeType.EDGE_DATACENTER)):
        parameters.enable_orchestrators = True
        parameters.deploy_orchestrator = mode
        engine, manager = build_manager(parameters, files, devices=10)
        task = manager.tasks[0]
        assert manager._select_orchestrator(task).type == expected, mode
    parameters.enable_orchestrators = False
    engine, manager = build_manager(parameters, files, devices=10)
    assert manager._select_orchestrator(manager.tasks[0]) is manager.tasks[0].source_device


def test_the_nearest_configured_orchestrator_is_used(parameters, files):
    parameters.enable_orchestrators = True
    parameters.deploy_orchestrator = "ANY"
    engine, manager = build_manager(parameters, files, devices=10)
    task = manager.tasks[0]
    # The example scenario declares no orchestrator node, so the registry takes over.
    assert manager._select_orchestrator(task) is manager.registry


def test_a_placed_application_sends_its_tasks_straight_to_the_same_node(parameters, files):
    engine, manager = build_manager(parameters, files, devices=10)
    task, other = manager.tasks[0], manager.tasks[1]
    destination = manager.nodes_generator.edge_data_centers[0]
    device = task.source_device
    device.application_placed = True
    device.application_placement_location = destination
    other.source_device = device
    before = destination.assigned_tasks
    manager._send_from_orchestrator_to_destination(other)
    assert other.destination is destination
    assert destination.assigned_tasks == before + 1
    assert manager.orchestrator.history[0] == 0


def test_the_container_is_downloaded_before_the_first_task_of_an_application(parameters, files):
    parameters.enable_registry = True
    parameters.registry_mode = "CLOUD"
    engine, manager = build_manager(parameters, files, "MIST_ONLY", devices=10)
    task = manager.tasks[0]
    destination = next(n for n in manager.orchestrator.candidates if n.type == NodeType.EDGE_DEVICE)
    # Pin the placement so the manager sends this task to a known mist node.
    task.source_device.application_placed = True
    task.source_device.application_placement_location = destination
    assert manager._needs_container(task, destination)
    manager._send_from_orchestrator_to_destination(task)
    assert destination.installed_containers == set()
    for _ in range(200):
        manager.network.update()
    assert destination.installed_containers == {task.application_id}
    assert manager.network.container_usage[LinkType.WAN] > 0
    assert task.status != TaskStatus.NO_OFFLOADING_DESTINATIONS


def test_a_cloud_destination_needs_no_container_download(parameters, files):
    parameters.enable_registry = True
    engine, manager = build_manager(parameters, files, devices=10)
    cloud = manager.nodes_generator.cloud_nodes[0]
    assert not manager._needs_container(manager.tasks[0], cloud)
    parameters.registry_mode = "CACHE"
    assert not manager._needs_container(manager.tasks[0], manager.edge_devices[0])


def test_the_device_reconnects_when_it_moves_to_another_data_center(parameters, files):
    engine, manager = build_manager(parameters, files, devices=10)
    device = manager.edge_devices[0]
    first = device.serving_edge_data_center
    other = manager.nodes_generator.edge_data_centers[0]
    manager.connect_with(device, other)
    assert device.serving_edge_data_center is other
    assert device.up_link.source is device and device.up_link.destination is other
    assert device.down_link.technology == device.up_link.technology
    manager.connect_with(device, None)
    assert device.serving_edge_data_center is other


def test_the_access_link_follows_the_destination(parameters, files):
    engine, manager = build_manager(parameters, files, devices=10)
    device = manager.edge_devices[0]
    cloud = manager.nodes_generator.cloud_nodes[0]
    assert manager.access_link(device, device.serving_edge_data_center) is device.up_link
    assert manager.access_link(device, cloud) is device.wan_up_link


def test_a_device_to_device_link_is_created_once_and_reused(parameters, files):
    engine, manager = build_manager(parameters, files, devices=10)
    parameters.edge_devices_range = 1e9
    source, target = manager.edge_devices[0], manager.edge_devices[1]
    first = manager.device_to_device_route(source, target)
    second = manager.device_to_device_route(source, target)
    assert first == second and isinstance(first[0], NetworkLink)
    assert len(manager.device_to_device_links) == 1
    assert manager.network.route_for(source, target) == first


def test_a_battery_that_gives_out_kills_one_device_and_its_pending_tasks(parameters, files):
    engine, manager = build_manager(parameters, files, "ALL", "TRADE_OFF", devices=10)
    victim = next(node for node in manager.edge_devices if node.is_battery_powered())
    # An idle draw that empties the battery after one simulated minute.
    victim.energy_model.idle_consumption = victim.energy_model.battery_capacity * 3600 / 60
    engine.start()
    assert victim.is_dead() and 0 < victim.death_time <= engine.clock
    assert [node for node in manager.edge_devices if node.is_dead()] == [victim]
    assert manager.metrics.dead_devices == 1
    assert manager.metrics.death_failures > 0
    assert manager.metrics.death_failures + manager.metrics.not_generated == sum(
        1 for task in manager.tasks if task.status == TaskStatus.FAILED_DUE_TO_DEVICE_DEATH)


def test_a_run_repeats_itself_with_the_same_seed(parameters, files):
    first_engine, first = run_manager(parameters, files, "ALL", "TRADE_OFF", devices=10, seed=5, iteration=3)
    second_engine, second = run_manager(parameters, files, "ALL", "TRADE_OFF", devices=10, seed=5, iteration=3)
    assert [task.id for task in first.tasks] == [task.id for task in second.tasks]
    assert [(task.time, task.length, task.request_size) for task in first.tasks[:20]] == \
        [(task.time, task.length, task.request_size) for task in second.tasks[:20]]
    assert first.metrics.succeeded_tasks == second.metrics.succeeded_tasks
    other_engine, other = run_manager(parameters, files, "ALL", "TRADE_OFF", devices=10, seed=5, iteration=4)
    assert [(task.time, task.length) for task in other.tasks[:20]] != \
        [(task.time, task.length) for task in first.tasks[:20]]


def test_a_short_run_ends_at_the_duration_when_the_workload_is_not_drained(parameters, files):
    parameters.wait_for_all_tasks = False
    engine, manager = run_manager(parameters, files, "ALL", "TRADE_OFF", devices=20)
    assert engine.clock <= manager.parameters.simulation_duration + 1


# ---------------------------------------------------------------------------
# Service graphs
# ---------------------------------------------------------------------------

def graph_files(files, latency=10):
    from dataclasses import replace

    from pureedgesim.config import Application, Subtask
    from pureedgesim.distribution import ConstantDistribution

    def node(name, dependencies=(), length=100.0):
        return Subtask(name=name, dependencies=dependencies, latency=ConstantDistribution(latency),
                       container_size=ConstantDistribution(8e6), request_size=ConstantDistribution(8e3),
                       results_size=ConstantDistribution(8e3), task_length=ConstantDistribution(length))

    application = Application(name="pipeline", type="pipeline", rate=ConstantDistribution(5),
                              usage_percentage=100, latency=ConstantDistribution(latency),
                              container_size=ConstantDistribution(8e6), request_size=ConstantDistribution(8e3),
                              results_size=ConstantDistribution(8e3), task_length=ConstantDistribution(100),
                              subtasks=(node("capture"), node("detect", ("capture",), 500.0),
                                        node("alert", ("detect",), 50.0)))
    return replace(files, applications=[application])


def test_the_subtasks_of_a_service_graph_run_in_dependency_order(parameters, files):
    engine, manager = run_manager(parameters, graph_files(files), devices=10)
    metrics = manager.metrics
    assert metrics.generated_tasks == len(manager.tasks) > 0
    assert metrics.succeeded_tasks == metrics.generated_tasks
    assert metrics.dependency_failures == 0
    assert engine.running is False
    for task in manager.tasks:
        for parent in task.dependencies:
            assert parent.execution_finish_time <= task.time


def test_a_failed_subtask_cancels_the_subtasks_that_depend_on_it(parameters, files):
    engine, manager = run_manager(parameters, graph_files(files, latency=0), devices=10)
    metrics = manager.metrics
    roots = [task for task in manager.tasks if not task.dependencies]
    dependents = [task for task in manager.tasks if task.dependencies]
    assert all(task.failed for task in roots)
    assert metrics.dependency_failures == len(dependents)
    assert all(task.status == TaskStatus.FAILED_BECAUSE_DEPENDENCY_FAILED for task in dependents)
    assert all(task.failed and task.id not in manager.finished_tasks for task in dependents)
    assert engine.running is False


def test_a_graph_scenario_reports_every_task_exactly_once(parameters, files):
    engine, manager = run_manager(parameters, graph_files(files, latency=0), devices=10)
    metrics = manager.metrics
    assert (metrics.succeeded_tasks + metrics.delay_failures + metrics.death_failures
            + metrics.mobility_failures + metrics.not_executed + metrics.not_generated
            + metrics.dependency_failures) == metrics.generated_tasks

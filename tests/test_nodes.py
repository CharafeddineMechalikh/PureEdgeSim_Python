"""Computing nodes: resources, execution queue, energy model and battery death."""
from __future__ import annotations

import pytest

from conftest import build_manager
from pyedgesim.nodes import BITS_PER_MB, ComputingNode, NodeStatus, NodeType
from pyedgesim.tasks import Task


@pytest.fixture
def running(parameters, files):
    return build_manager(parameters, files, devices=100)


def make_task(node, length=1000.0, container=8 * 1000 * 1000, request=8000, result=8000, latency=1e9):
    return Task(id=1, type="test", application_id=0, length=length, container_size=container,
                request_size=request, result_size=result, max_latency=latency, time=0.0,
                source_device=node, registry=node)


def test_container_size_is_expressed_in_mb(running):
    engine, manager = running
    node = manager.nodes_generator.cloud_nodes[0]
    task = make_task(node, container=BITS_PER_MB * 2.5)
    assert node.get_container_mb(task) == pytest.approx(2.5)


def test_device_percentages_are_rounded_down_then_filled_with_the_last_type(parameters, files):
    engine, manager = build_manager(parameters, files, devices=50)
    # The scenario has five device types (18, 11, 11, 28 and 32 %). Of 50 devices
    # that is 9, 5, 5, 14 and 16, and the two missing ones are instances of the
    # last device type, exactly like PureEdgeSim tops the count up.
    assert len(manager.edge_devices) == 50
    assert sum(1 for n in manager.edge_devices if n.is_battery_powered()) == 9 + 5
    assert sum(1 for n in manager.edge_devices if not n.is_sensor) == 9 + 5 + 5


def test_submit_reserves_storage_and_starts_when_a_core_is_free(running):
    engine, manager = running
    node = manager.nodes_generator.cloud_nodes[0]
    task = make_task(node, container=min(node.available_ram, node.available_storage) / 2 * BITS_PER_MB)
    storage_before = node.available_storage
    node.submit_task(task)
    assert node.available_storage == pytest.approx(storage_before - node.get_container_mb(task))
    assert node.executing_tasks == [task]
    assert node.task_queue == []
    assert task.execution_start_time == engine.clock


def test_execution_is_queued_behind_a_busy_device(running):
    engine, manager = running
    node = next(n for n in manager.computing_nodes if not n.is_sensor)
    node.cores = node.free_cores = 1
    first, second = make_task(node), make_task(node)
    node.submit_task(first)
    node.submit_task(second)
    assert node.executing_tasks == [first]
    assert node.task_queue == [second]


def test_execution_time_uses_one_core_only(running):
    engine, manager = running
    node = next(n for n in manager.computing_nodes if n.cores >= 2 and not n.is_sensor)
    task = make_task(node, length=node.mips_per_core * 3)
    node.submit_task(task)
    assert task.execution_duration == pytest.approx(3.0)
    assert node.free_cores == node.cores - 1


def test_finished_task_frees_every_resource(running):
    engine, manager = running
    node = manager.nodes_generator.cloud_nodes[0]
    storage_before, ram_before = node.available_storage, node.available_ram
    task = make_task(node, length=10.0)
    node.submit_task(task)
    node.execution_finished(task)
    assert (node.available_storage, node.available_ram) == (storage_before, ram_before)
    assert node.free_cores == node.cores
    assert node.total_executed_instructions == pytest.approx(10.0)


def test_ram_is_refused_when_the_container_does_not_fit(running):
    engine, manager = running
    node = manager.nodes_generator.cloud_nodes[0]
    task = make_task(node, container=(node.available_ram + 1) * BITS_PER_MB)
    assert not node.is_ram_available(task)
    assert not node.has_enough_resources(task)


def test_static_energy_is_charged_once_per_update(running):
    engine, manager = running
    node = manager.edge_devices[0]
    idle = node.energy_model.idle_consumption
    before = node.energy_model.cpu_energy_consumption
    node.update_status()
    assert node.energy_model.cpu_energy_consumption - before == pytest.approx(
        idle / 3600 * manager.parameters.update_interval)


def test_dynamic_energy_uses_the_power_delta(running):
    engine, manager = running
    node = manager.nodes_generator.cloud_nodes[0]
    delta = node.energy_model.max_consumption - node.energy_model.idle_consumption
    before = node.energy_model.cpu_energy_consumption
    node.energy_model.add_dynamic_energy(1000.0, node.total_mips)
    assert node.energy_model.cpu_energy_consumption - before == pytest.approx(
        delta / 3600 * 1000.0 / node.total_mips)


def test_wireless_energy_labels_are_inverted_on_purpose(running):
    engine, manager = running
    model = manager.edge_devices[0].energy_model
    from pyedgesim.nodes import RECEPTION, TRANSMISSION
    model.network_energy_consumption = 0.0
    model.update_wireless_energy_consumption(1000.0, RECEPTION)
    assert model.network_energy_consumption == pytest.approx(1000.0 * model.transmission_energy_per_bit)
    model.network_energy_consumption = 0.0
    model.update_wireless_energy_consumption(1000.0, TRANSMISSION)
    assert model.network_energy_consumption == pytest.approx(1000.0 * model.reception_energy_per_bit)


def test_connectivity_selects_the_energy_rates(parameters, files):
    parameters.cellular_device_transmission_energy = 1e-10
    engine, manager = build_manager(parameters, files, devices=100)
    model = manager.edge_devices[0].energy_model
    model.set_connectivity_type("cellular", parameters)
    assert model.transmission_energy_per_bit == 1e-10
    model.set_connectivity_type("ethernet", parameters)
    assert model.transmission_energy_per_bit == pytest.approx(parameters.ethernet_energy_per_bit / 2)


def test_battery_starts_partially_drained(parameters, files):
    engine, manager = build_manager(parameters, files, devices=100)
    node = next((n for n in manager.edge_devices if n.is_battery_powered()), None)
    if node is None:
        pytest.skip("the scenario has no battery powered device")
    expected = node.energy_model.battery_capacity * (1 - node.energy_model.initial_battery_level / 100)
    assert node.energy_model.cpu_energy_consumption == pytest.approx(expected)


def test_a_device_dies_when_the_battery_is_empty(running):
    engine, manager = running
    node = manager.edge_devices[0]
    node.energy_model.battery_powered = True
    node.energy_model.battery_capacity = node.energy_model.get_total_energy_consumption()
    node.update_status()
    assert node.status == NodeStatus.DEAD
    assert node.death_time == engine.clock
    assert node.is_battery_empty()


def test_a_dead_device_stops_updating_and_keeps_its_death_time(running):
    """PureEdgeSim returns early once a node is dead, so it is marked dead only once."""
    engine, manager = running
    node = manager.edge_devices[0]
    node.energy_model.battery_powered = True
    node.energy_model.battery_capacity = node.energy_model.get_total_energy_consumption()
    engine.clock = 30.0
    node.update_status()
    engine.clock = 90.0
    node.update_status()
    assert node.status == NodeStatus.DEAD
    assert node.death_time == 30.0
    assert node.get_remaining_battery_percentage() == 0.0


def test_cpu_usage_measures_instructions_over_capacity(running):
    engine, manager = running
    node = manager.nodes_generator.cloud_nodes[0]
    engine.clock = 30.0
    node.total_executed_instructions = node.total_mips * 15
    assert node.get_cpu_usage_average() == pytest.approx(50.0)
    node.total_executed_instructions = node.total_mips * 1000
    assert node.get_cpu_usage_average() == 100.0


def test_current_cpu_usage_follows_the_running_tasks(running):
    engine, manager = running
    node = manager.nodes_generator.cloud_nodes[0]
    node.executing_tasks.append(make_task(node, length=node.total_mips * 0.5))
    assert node.get_cpu_usage_current() == pytest.approx(50.0)


def test_a_zero_core_node_is_a_sensor(running):
    engine, manager = running
    assert manager.nodes_generator.routers[0].is_sensor
    assert manager.nodes_generator.routers[0].get_cpu_usage_average() == 0.0


def test_null_node_is_dead_and_has_no_data_center(running):
    engine, manager = running
    assert ComputingNode.NULL.is_dead()
    assert not ComputingNode.NULL.is_alive()
    assert manager.network.route_for(ComputingNode.NULL, ComputingNode.NULL) == []


def test_every_node_type_is_registered(running):
    engine, manager = running
    assert manager.nodes_generator.cloud_nodes[0].type == NodeType.CLOUD
    assert manager.nodes_generator.edge_data_centers[0].type == NodeType.EDGE_DATACENTER
    assert manager.edge_devices[0].type == NodeType.EDGE_DEVICE
    assert manager.nodes_generator.routers[0].type == NodeType.ROUTER

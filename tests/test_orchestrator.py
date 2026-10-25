"""Orchestration: placement layers, eligibility, and the two algorithms."""
from __future__ import annotations

import pytest

from conftest import build_manager
from pureedgesim import NodeType, Task
from pureedgesim.orchestrator import LAYERS, WEIGHTS, Orchestrator


def make_task(device, length=1000.0):
    return Task(id=1, type="test", application_id=0, length=length, container_size=8e6,
                request_size=8e3, result_size=8e3, max_latency=1e9, time=0.0,
                source_device=device, registry=device)


@pytest.fixture
def orch(parameters, files):
    engine, manager = build_manager(parameters, files, devices=100)
    return engine, manager, manager.orchestrator


def test_the_seven_architectures_are_the_java_layers():
    assert set(LAYERS) == {"CLOUD_ONLY", "EDGE_ONLY", "MIST_ONLY", "MIST_AND_CLOUD", "EDGE_AND_CLOUD",
                           "MIST_AND_EDGE", "ALL"}
    assert LAYERS["ALL"] == (NodeType.EDGE_DEVICE, NodeType.EDGE_DATACENTER, NodeType.CLOUD)
    assert LAYERS["MIST_AND_EDGE"] == (NodeType.EDGE_DEVICE, NodeType.EDGE_DATACENTER)


def test_unknown_architectures_leave_no_candidate(orch):
    engine, manager, orchestrator = orch
    orchestrator.initialize("NOTHING")
    assert orchestrator.architecture_layers == ()
    assert orchestrator.candidates == []


def test_candidates_are_the_non_sensor_nodes_of_the_layer(parameters, files):
    for architecture in ("CLOUD_ONLY", "MIST_ONLY", "EDGE_ONLY", "ALL"):
        engine, manager = build_manager(parameters, files, architecture, devices=100)
        orchestrator = manager.orchestrator
        assert {node.type for node in orchestrator.candidates} == set(LAYERS[architecture])
        assert all(not node.is_sensor for node in orchestrator.candidates)
        if architecture == "CLOUD_ONLY":
            assert len(orchestrator.candidates) == len(manager.nodes_generator.cloud_nodes)


def test_trade_off_score_uses_the_layer_weight(orch):
    engine, manager, orchestrator = orch
    device = manager.edge_devices[0]
    task = make_task(device)
    cloud = manager.nodes_generator.cloud_nodes[0]
    assert Orchestrator.score(cloud, task) == pytest.approx(
        (cloud.assigned_tasks + 1) * 1.8 * task.length / cloud.mips_per_core)
    assert WEIGHTS == {NodeType.CLOUD: 1.8, NodeType.EDGE_DATACENTER: 1.2, NodeType.EDGE_DEVICE: 1.3}


def test_trade_off_selects_the_eligible_node_with_the_lowest_score(orch):
    engine, manager, orchestrator = orch
    device = manager.edge_devices[0]
    manager.parameters.edge_devices_range = 1e9
    orchestrator.initialize("ALL")
    task = make_task(device, length=1e6)
    destination = orchestrator.orchestrate(task, 0)
    scores = {index: Orchestrator.score(node, task)
              for index, node in enumerate(orchestrator.candidates)
              if orchestrator.offloading_is_possible(node, task)}
    assert destination is orchestrator.candidates[min(scores, key=scores.get)]
    assert task.destination is destination
    # The placement is counted by the algorithm, not on the node.
    assert orchestrator.history[orchestrator.candidates.index(destination)] == 1
    assert destination.assigned_tasks == 0


def test_trade_off_moves_away_from_a_node_it_already_used(orch):
    engine, manager, orchestrator = orch
    manager.parameters.edge_devices_range = 1e9
    orchestrator.initialize("MIST_ONLY")
    device = next(n for n in manager.edge_devices if not n.is_sensor)
    first = orchestrator.orchestrate(make_task(device, length=1e6), 0)
    # The score grows with (history + 1), so the second task goes elsewhere unless
    # the same node is still twice as fast as every other candidate.
    second = orchestrator.orchestrate(make_task(device, length=1e6), 0)
    assert orchestrator.history[orchestrator.candidates.index(first)] == 2 or second is not first


def test_trade_off_avoids_the_cloud_when_only_mist_is_allowed(orch):
    engine, manager, orchestrator = orch
    manager.parameters.edge_devices_range = 1e9
    orchestrator.initialize("MIST_ONLY")
    task = make_task(manager.edge_devices[0])
    assert orchestrator.orchestrate(task, 0).type == NodeType.EDGE_DEVICE


def test_round_robin_spreads_the_load(parameters, files):
    engine, manager = build_manager(parameters, files, algorithm="ROUND_ROBIN", devices=100)
    orchestrator = manager.orchestrator
    manager.parameters.edge_devices_range = 1e9
    orchestrator.initialize("MIST_AND_EDGE")
    device = next(n for n in manager.edge_devices
                  if n.serving_edge_data_center is not None and not n.is_sensor)
    eligible = [node for node in orchestrator.candidates
                if orchestrator.offloading_is_possible(node, make_task(device))]
    assert device.serving_edge_data_center in eligible
    choices = [orchestrator.orchestrate(make_task(device), 0) for _ in range(len(eligible))]
    # Every candidate is used exactly once before any of them is reused, whatever
    # its speed or layer: round robin ignores the task length and the weights.
    assert sorted(id(node) for node in choices) == sorted(id(node) for node in eligible)
    assert set(orchestrator.history.values()) == {1}


def test_the_scenario_algorithm_drives_the_placement(parameters, files):
    engine, first = build_manager(parameters, files, "MIST_AND_EDGE", "TRADE_OFF", 100)
    engine, second = build_manager(parameters, files, "MIST_AND_EDGE", "ROUND_ROBIN", 100)
    for manager in (first, second):
        manager.parameters.edge_devices_range = 1e9
    # Same seed and same topology, so the two managers hold the same nodes in the
    # same order; only the algorithm differs.
    device = next(n for n in first.edge_devices
                  if n.serving_edge_data_center is not None and not n.is_sensor)
    eligible = [node for node in first.orchestrator.candidates
                 if first.orchestrator.offloading_is_possible(node, make_task(device))]
    trade_off = first.orchestrator.orchestrate(make_task(device, length=1e6), 0)
    round_robin = second.orchestrator.orchestrate(make_task(device, length=1e6), 0)
    # Trade-off scores every candidate and takes the fastest one per weighted MIPS;
    # round robin ignores all of that and walks the list.
    assert trade_off.mips_per_core == max(node.mips_per_core for node in eligible)
    eligible_second = [index for index, node in enumerate(second.orchestrator.candidates)
                       if second.orchestrator.offloading_is_possible(node, make_task(device))]
    assert second.orchestrator.candidates.index(round_robin) == eligible_second[0]


def test_a_mist_destination_must_be_within_radio_range(orch):
    engine, manager, orchestrator = orch
    manager.parameters.edge_devices_range = 0.001
    orchestrator.initialize("MIST_ONLY")
    device = manager.edge_devices[0]
    others = [n for n in orchestrator.candidates if n is not device]
    assert all(not orchestrator.offloading_is_possible(node, make_task(device)) for node in others)


def test_an_edge_data_center_is_only_reachable_through_its_own_access(orch):
    engine, manager, orchestrator = orch
    orchestrator.initialize("EDGE_ONLY")
    device = manager.edge_devices[0]
    serving = device.serving_edge_data_center
    task = make_task(device)
    assert orchestrator.offloading_is_possible(serving, task)
    for other in manager.nodes_generator.edge_data_centers:
        if other is not serving:
            assert not orchestrator.offloading_is_possible(other, task)


def test_a_dead_device_is_never_a_candidate(orch):
    engine, manager, orchestrator = orch
    from pureedgesim.nodes import NodeStatus
    manager.parameters.edge_devices_range = 1e9
    orchestrator.initialize("MIST_ONLY")
    device = manager.edge_devices[0]
    candidate = orchestrator.candidates[0]
    candidate.status = NodeStatus.DEAD
    assert not orchestrator.offloading_is_possible(candidate, make_task(device))


def test_no_eligible_node_means_no_destination(orch):
    from pureedgesim.nodes import NodeStatus
    engine, manager, orchestrator = orch
    orchestrator.initialize("MIST_ONLY")
    for candidate in orchestrator.candidates:
        candidate.status = NodeStatus.DEAD
    device = manager.edge_devices[0]
    assert orchestrator.find_computing_node([make_task(device)], "TRADE_OFF", 0) == -1
    assert orchestrator.orchestrate(make_task(device), 0) is None
    assert orchestrator.history[0] == 0


def test_the_selected_node_is_recorded_as_the_device_placement(orch):
    engine, manager, orchestrator = orch
    manager.parameters.edge_devices_range = 1e9
    orchestrator.initialize("ALL")
    device = manager.edge_devices[0]
    task = make_task(device)
    destination = orchestrator.orchestrate(task, 0)
    assert device.application_placed
    assert device.application_placement_location is destination
    assert task.destination is destination


def test_a_custom_orchestrator_replaces_the_default_one(parameters, files):
    from conftest import build_manager
    calls = []

    class Recording(Orchestrator):
        def orchestrate(self, task, application_id=0):
            calls.append(task.id)
            return None

    engine, manager = build_manager(parameters, files, devices=5)
    manager.orchestrator = Recording(manager)
    manager.orchestrator.initialize("ALL")
    assert manager.tasks
    for task in manager.tasks[:2]:
        manager._send_from_orchestrator_to_destination(task)
    assert calls == [task.id for task in manager.tasks[:2]]
    assert manager.metrics.not_executed == 2

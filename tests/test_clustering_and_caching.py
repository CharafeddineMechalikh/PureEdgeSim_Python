"""The Example7 clustering and cooperative caching port, checked on its own settings.

The example wires two extension points at once: a topology creator that clusters
the devices under elected heads, and a network model that serves a container
download from the cluster head instead of the WAN registry. It is covered twice,
the way the other hook examples are. As a mechanism first, on a real tiny
manager: the head election has to group a neighbourhood, the cluster links and
the published orchestrators have to appear in the graph, and the cooperative
cache has to answer a request from a cluster replica. As a script second: its
``main`` entry point, shrunk to a handful of devices and two simulated minutes,
has to leave one CSV with two rows, the cached run and the registry run, sharing
the same workload, and the cached run has to move container traffic off the WAN.
"""
from __future__ import annotations

import csv

import pytest

from examples.clustering_and_caching.clustering_and_caching import (
    CooperativeCacheNetworkModel, ClusterTopologyCreator, SETTINGS, elect_heads,
    load_example_parameters, main)
from pureedgesim import (COLUMNS, Engine, NodeType, Randomness, Scenario, SimulationManager, load_settings)

# Two simulated minutes generates a burst of tasks for every application, and a
# 24-device map keeps the clusters small enough that a replica is shared, while the
# seed fixes both the workload and the device positions.
SHORT_DURATION = 120.0
SEED = 71
DEVICES = 24


def scenario_of(parameters) -> Scenario:
    return Scenario(parameters.orchestration_architectures[0], parameters.orchestration_algorithms[0],
                    parameters.max_number_of_devices)


def build(cache: bool, devices: int = DEVICES, duration: float = SHORT_DURATION, seed: int = SEED):
    """An un-run engine and manager with the Example7 hooks wired onto the manager."""
    parameters = load_example_parameters(devices, duration, seed)
    Randomness.set_seed(seed)
    Randomness.begin_scenario(0)
    engine = Engine(parameters.simulation_duration)
    manager = SimulationManager(engine, parameters, load_settings(SETTINGS), scenario_of(parameters),
                                custom_topology_creator=ClusterTopologyCreator,
                                custom_network_model=CooperativeCacheNetworkModel if cache else None)
    manager.start_simulation()
    return engine, manager


def read_rows(folder):
    path = next(folder.rglob("Sequential_simulation.csv"))
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# --------------------------------------------------------------------------- clustering

def test_the_election_groups_a_neighbourhood_around_a_head():
    engine, manager = build(cache=False)
    head_of = manager.cluster_head_of
    members = manager.cluster_members
    # Every device follows pointers to a head, and a head is a device that points to
    # itself: the head of a head is itself, so no cluster is a chain into nothing.
    assert len(members) > 1
    for identifier, head in head_of.items():
        assert head_of[head] == head
        assert identifier in members[head]
    assert sum(len(group) for group in members.values()) == len(head_of)
    assert any(len(group) > 1 for group in members.values())


def test_clustering_wires_links_and_publishes_heads_as_orchestrators():
    engine, manager = build(cache=False)
    generator = manager.nodes_generator
    # Each cluster head the election found is now on the orchestrators list, the hook
    # that lets deploy_orchestrator=CLUSTER place the orchestrator on a head.
    for head_id in manager.cluster_members:
        head = next(node for node in generator.edge_devices if node.id == head_id)
        assert head.is_orchestrator
        assert head in generator.orchestrators
    # A member that follows a different head gained a directed link to it.
    graph = manager.network.graph
    for member_id, head_id in manager.cluster_head_of.items():
        if member_id == head_id:
            continue
        member = next(node for node in generator.edge_devices if node.id == member_id)
        head = next(node for node in generator.edge_devices if node.id == head_id)
        assert graph.shortest_path(member, head)


def test_elect_heads_is_a_pure_grouping_of_the_input():
    engine, manager = build(cache=False, devices=10)
    devices = [node for node in manager.nodes_generator.edge_devices if not node.is_sensor]
    heads = elect_heads(devices, manager.parameters.edge_devices_range)
    # A lone device is its own head; every mapped head really is in the input.
    by_id = {node.id: node for node in devices}
    assert set(heads) == set(by_id)
    for identifier, head in heads.items():
        assert head in by_id
        assert heads[head] == head


# --------------------------------------------------------------------------- caching

def test_the_cooperative_cache_serves_a_container_from_the_cluster():
    engine, manager = build(cache=True)
    engine.start()
    network = manager.network
    assert isinstance(network, CooperativeCacheNetworkModel)
    # The mechanism fired: some request was answered from a cluster replica over the
    # LAN instead of the registry, and some application still had to cross the WAN.
    assert network.served_from_cache > 0
    assert network.pulled_from_registry > 0
    assert "served locally" in network.cache_report()


def test_the_cache_moves_container_traffic_off_the_wan():
    from pureedgesim import summarize

    cached_engine, cached = build(cache=True)
    cached_engine.start()
    cached_row = summarize(cached)

    plain_engine, plain = build(cache=False)
    plain_engine.start()
    plain_row = summarize(plain)

    # Same workload, same clustering, the cooperative model is the only difference:
    # the cached run pays the registry less often and serves some replicas on the LAN.
    assert cached_row[COLUMNS[7]] == plain_row[COLUMNS[7]]
    assert cached_row[COLUMNS[25]] < plain_row[COLUMNS[25]]
    assert cached_row[COLUMNS[26]] > 0.0


def test_a_run_without_clusters_leaves_the_cache_idle():
    # With the cooperative model but no cluster map the gate is closed, so the
    # network model stays the plain default and the downloads are never intercepted.
    parameters = load_example_parameters(DEVICES, SHORT_DURATION, SEED)
    Randomness.set_seed(SEED)
    Randomness.begin_scenario(0)
    engine = Engine(parameters.simulation_duration)
    manager = SimulationManager(engine, parameters, load_settings(SETTINGS), scenario_of(parameters),
                                custom_network_model=CooperativeCacheNetworkModel)
    manager.start_simulation()
    assert not manager.network._cooperative_enabled()


# --------------------------------------------------------------------------- script

def test_the_script_writes_the_cached_and_registry_rows(tmp_path):
    row = main(devices=DEVICES, duration=SHORT_DURATION, seed=SEED, output=tmp_path)
    assert row[COLUMNS[19]] > 0
    rows = read_rows(tmp_path)
    assert len(rows) == 2
    cached, registry = rows
    assert float(cached[COLUMNS[7]]) == float(registry[COLUMNS[7]])
    assert float(cached[COLUMNS[22]]) < float(registry[COLUMNS[22]])
    assert float(cached[COLUMNS[26]]) > 0.0
    assert float(registry[COLUMNS[26]]) == 0.0

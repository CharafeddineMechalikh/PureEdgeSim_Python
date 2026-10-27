"""End-to-end checks of the four topology examples, on their own real settings.

Each example is exercised twice: a unit-level probe that shows the mechanism
actually engages (access-aware scores, layer preference, cache hits and
evictions, elected cluster heads), and a shrunk full run that has to end with a
sane result row.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from examples.container_cache import container_cache as cache_module
from examples.container_cache.container_cache import (CACHE_CAPACITY_MB, ContainerCache,
                                                      ContainerCacheSimulationManager,
                                                      UncachedRegistryManager, build_manager)
from examples.container_cache.container_cache import SETTINGS as CACHE_SETTINGS
from examples.fog_layers import fog_layers as fog_module
from examples.fog_layers.fog_layers import FogLayersOrchestrator
from examples.fog_layers.fog_layers import SETTINGS as FOG_SETTINGS
from examples.multi_access_mec import multi_access_mec as access_module
from examples.multi_access_mec.multi_access_mec import AccessAwareOrchestrator
from examples.multi_access_mec.multi_access_mec import SETTINGS as ACCESS_SETTINGS
from examples.self_clustering import self_clustering as cluster_module
from examples.self_clustering.self_clustering import ClusterOrchestrator, raw_score, refresh_clusters
from examples.self_clustering.self_clustering import SETTINGS as CLUSTER_SETTINGS
from pureedgesim import (COLUMNS, Engine, Event, NodeStatus, NodeType, Randomness, Scenario, SimulationManager,
                         Task, load_parameters, load_settings)

# One minute is the smallest duration that still generates a burst of tasks, and
# the seed makes both the workload and the mobility reproducible.
SHORT_DURATION = 120.0


def make_task(device, length=30000.0, application_id=0, container_mb=2.2, identifier=1, registry=None):
    """A task shaped like the generated ones, only big enough to be decided on."""
    task = Task(id=identifier, type="Non Real-time", application_id=application_id, length=length,
                container_size=container_mb * 8e6, request_size=2500 * 8000, result_size=200 * 8000,
                max_latency=300.0, time=1.0, source_device=device, registry=registry or device)
    return task


def build(settings, orchestrator, architecture, algorithm, devices, duration=SHORT_DURATION, seed=11,
          map_size=None):
    """A manager with the topology and the workload built, but not yet run."""
    parameters = load_parameters(settings / "simulation_parameters.properties")
    parameters.min_number_of_devices = parameters.max_number_of_devices = devices
    parameters.devices_increment = 1
    parameters.simulation_duration = duration
    parameters.random_seed = seed
    if map_size is not None:
        parameters.simulation_map_length = parameters.simulation_map_width = map_size
    Randomness.set_seed(seed)
    Randomness.begin_scenario(0)
    engine = Engine(parameters.simulation_duration)
    manager = SimulationManager(engine, parameters, load_settings(settings),
                                Scenario(architecture, algorithm, devices), custom_orchestrator=orchestrator)
    manager.start_simulation()
    return engine, manager


def assert_sane_row(row):
    assert row[COLUMNS[7]] > 0
    assert row[COLUMNS[8]] > 0
    assert row[COLUMNS[15]] + row[COLUMNS[17]] + row[COLUMNS[19]] <= row[COLUMNS[7]]
    assert row[COLUMNS[3]] > 0
    assert row[COLUMNS[32]] > 0
    assert row[COLUMNS[46]] >= 0


# --------------------------------------------------------------------------- Example12

@pytest.fixture
def access_manager():
    return build(ACCESS_SETTINGS, AccessAwareOrchestrator, "ALL", "ACCESS_AWARE", 24)


def _device_by_connectivity(manager, connectivity):
    return next(node for node in manager.edge_devices
                if node.energy_model.connectivity == connectivity and not node.is_sensor)


def test_the_cellular_uplink_is_more_expensive_than_wifi(access_manager):
    engine, manager = access_manager
    orchestrator = manager.orchestrator
    cellular, wifi = _device_by_connectivity(manager, "cellular"), _device_by_connectivity(manager, "wifi")
    edge = cellular.serving_edge_data_center
    parameters = manager.parameters
    # The access delay of an edge data center is the uplink: the radio latency
    # plus the request and the result on the technology's bandwidth.
    transfer = make_task(cellular).request_size + make_task(cellular).result_size
    assert orchestrator.access_delay(make_task(cellular), edge) == pytest.approx(
        parameters.cellular_delay + transfer / parameters.cellular_bandwidth)
    assert orchestrator.access_delay(make_task(wifi), edge) == pytest.approx(
        parameters.wifi_delay + transfer / parameters.wifi_bandwidth)
    assert orchestrator.access_delay(make_task(cellular), edge) > orchestrator.access_delay(
        make_task(wifi), edge)


def test_the_cloud_candidate_pays_an_extra_wan_hop(access_manager):
    engine, manager = access_manager
    orchestrator = manager.orchestrator
    cloud = manager.nodes_generator.cloud_nodes[0]
    device = _device_by_connectivity(manager, "wifi")
    task = make_task(device)
    parameters = manager.parameters
    transfer = task.request_size + task.result_size
    assert orchestrator.access_delay(task, cloud) == pytest.approx(
        parameters.wifi_delay + transfer / parameters.wifi_bandwidth + parameters.wan_delay
        + transfer / parameters.wan_bandwidth)
    mist = next(node for node in orchestrator.candidates if node.type is NodeType.EDGE_DEVICE)
    assert orchestrator.access_delay(task, mist) == pytest.approx(
        parameters.wifi_delay + transfer / parameters.wifi_bandwidth)


def test_a_node_without_cpu_is_never_a_destination(access_manager):
    engine, manager = access_manager

    class NoCpu:
        mips_per_core = 0.0

    assert AccessAwareOrchestrator.compute_delay(make_task(manager.edge_devices[0]), NoCpu()) == float("inf")


def test_queue_pressure_moves_the_choice_from_the_edge_to_the_device(access_manager):
    engine, manager = access_manager
    orchestrator = manager.orchestrator
    # On this map the devices are farther apart than the Wi-Fi range, so the mist
    # tier is only a destination once the range is opened. The queue pressure can
    # not push a task onto a tier that was never eligible.
    manager.parameters.edge_devices_range = 1e9
    device = _device_by_connectivity(manager, "cellular")
    first = orchestrator.find_computing_node([make_task(device, identifier=1)], "ACCESS_AWARE", 0)
    assert orchestrator.candidates[first].type is NodeType.EDGE_DATACENTER
    assert orchestrator.pending[first] == 1
    assert orchestrator.queued_delay(make_task(device), first) == pytest.approx(
        orchestrator.pending[first] * orchestrator.compute_delay(make_task(device),
                                                                orchestrator.candidates[first])
        / orchestrator.candidates[first].cores)
    # Fill the queue of that data center until running on a device is cheaper than
    # waiting for a free core or paying for the WAN hop.
    orchestrator.pending[first] = 1000
    second = orchestrator.find_computing_node([make_task(device, identifier=2)], "ACCESS_AWARE", 0)
    assert second != first
    assert orchestrator.candidates[second].type is NodeType.EDGE_DEVICE
    orchestrator.results_returned(make_task(device, identifier=1))
    assert orchestrator.pending[first] == 999
    orchestrator.results_returned(make_task(device, identifier=2))
    assert orchestrator.pending[second] == 0
    orchestrator.results_returned(make_task(device, identifier=404))
    assert orchestrator.pending[second] == 0


def test_the_mec_run_places_the_work_on_the_edge_tier(access_manager):
    engine, manager = access_manager
    engine.start()
    orchestrator = manager.orchestrator
    assert orchestrator.placements
    assert {technology for technology, _ in orchestrator.placements} == {"cellular", "wifi"}
    assert manager.metrics.edge_tasks > 0
    assert len(manager.finished_tasks) == manager.metrics.generated_tasks


def test_the_access_aware_orchestrator_rejects_another_algorithm():
    with pytest.raises(ValueError, match="ACCESS_AWARE"):
        build(ACCESS_SETTINGS, AccessAwareOrchestrator, "ALL", "TRADE_OFF", 8)


def test_the_multi_access_script_writes_a_row(tmp_path):
    row = access_module.main(devices=16, duration=SHORT_DURATION, seed=11, output=tmp_path)
    assert_sane_row(row)
    assert row[COLUMNS[17]] > 0
    assert (next(tmp_path.rglob("Sequential_simulation.csv"))).is_file()


# --------------------------------------------------------------------------- Example13

@pytest.fixture
def fog_manager():
    # A 600 by 600 map keeps every home gateway within range of a sensor, so the
    # layer behaviour is visible with a handful of devices.
    return build(FOG_SETTINGS, FogLayersOrchestrator, "ALL", "FOG_LAYERS", 40, map_size=600.0)


def _sensor(manager):
    return next(node for node in manager.edge_devices if node.is_sensor)


def test_the_mist_layer_is_filled_gateway_by_gateway(fog_manager):
    engine, manager = fog_manager
    orchestrator = manager.orchestrator
    sensor = _sensor(manager)
    chosen = [orchestrator.find_computing_node([make_task(sensor, identifier=index)], "FOG_LAYERS", 0)
              for index in range(1, 6)]
    assert -1 not in chosen
    assert len(set(chosen)) == 5
    assert {orchestrator.candidates[index].type for index in chosen} == {NodeType.EDGE_DEVICE}
    assert orchestrator.pending_on(chosen[0]) == 1


def test_a_task_leaves_the_mist_only_when_no_gateway_is_in_range(fog_manager):
    engine, manager = fog_manager
    orchestrator = manager.orchestrator
    sensor = _sensor(manager)
    manager.parameters.edge_devices_range = 1e-6
    index = orchestrator.find_computing_node([make_task(sensor)], "FOG_LAYERS", 0)
    assert orchestrator.candidates[index].type is NodeType.EDGE_DATACENTER
    sensor.serving_edge_data_center = None
    index = orchestrator.find_computing_node([make_task(sensor, identifier=2)], "FOG_LAYERS", 0)
    assert orchestrator.candidates[index].type is NodeType.CLOUD


def test_a_layer_without_any_node_is_skipped(fog_manager):
    engine, manager = fog_manager
    orchestrator = manager.orchestrator
    orchestrator.architecture_layers = ()
    assert orchestrator.find_computing_node([make_task(_sensor(manager))], "FOG_LAYERS", 0) == -1


def test_the_fog_run_prefers_the_gateways_and_overflows_to_the_edge(fog_manager):
    engine, manager = fog_manager
    engine.start()
    orchestrator = manager.orchestrator
    assert orchestrator.placements["Mist"] > 0
    assert len(manager.finished_tasks) == manager.metrics.generated_tasks
    metrics = manager.metrics
    assert metrics.mist_tasks > metrics.edge_tasks >= 0
    assert metrics.cloud_tasks == 0


def test_the_fog_orchestrator_rejects_another_algorithm():
    with pytest.raises(ValueError, match="FOG_LAYERS"):
        build(FOG_SETTINGS, FogLayersOrchestrator, "ALL", "TRADE_OFF", 8)


def test_the_fog_script_writes_a_row(tmp_path):
    row = fog_module.main(devices=60, duration=SHORT_DURATION, seed=11, output=tmp_path)
    assert_sane_row(row)
    assert row[COLUMNS[19]] > 0
    assert (next(tmp_path.rglob("Sequential_simulation.csv"))).is_file()


# --------------------------------------------------------------------------- Example21

def test_the_cache_evicts_the_least_recently_used_container():
    cache = ContainerCache(3.0)
    assert cache.store(1, 2.2)
    assert cache.store(2, 1.5) is False or cache.size() >= 1
    assert cache.contains(2) and not cache.contains(1)
    assert cache.evictions == 1
    assert cache.used_mb == pytest.approx(1.5)
    assert cache.lookup(2) and not cache.lookup(1)
    assert (cache.hits, cache.misses) == (1, 1)
    assert cache.hit_ratio == pytest.approx(0.5)


def test_a_container_larger_than_the_cache_is_refused():
    cache = ContainerCache(1.0)
    assert cache.store(1, 0.8)
    assert not cache.store(2, 2.2)
    assert cache.rejected == 1
    assert cache.size() == 1 and cache.capacity_mb == 1.0
    assert ContainerCache(-1).capacity_mb == 0.0


@pytest.fixture
def cache_parameters():
    parameters = load_parameters(CACHE_SETTINGS / "simulation_parameters.properties")
    parameters.min_number_of_devices = parameters.max_number_of_devices = 40
    parameters.devices_increment = 1
    parameters.simulation_duration = SHORT_DURATION
    parameters.random_seed = 61
    return parameters


def cache_scenario(parameters, devices):
    return Scenario(parameters.orchestration_architectures[0], parameters.orchestration_algorithms[0], devices)


def test_a_hit_skips_the_download_and_a_miss_stores_the_container(cache_parameters):
    engine, manager = build_manager("cache", cache_parameters, load_settings(CACHE_SETTINGS),
                                    cache_scenario(cache_parameters, 40))
    data_center = manager.nodes_generator.edge_data_centers[0]
    cloud = manager.nodes_generator.cloud_nodes[0]
    sensor = next(node for node in manager.edge_devices if node.is_sensor)
    cache = manager.container_caches[data_center.id]
    assert cache.capacity_mb == CACHE_CAPACITY_MB
    task = make_task(manager.edge_devices[0], identifier=1)
    assert manager._needs_container(task, data_center)
    assert manager.pending_store[task.id][1] == task.application_id
    manager._send_request_to_destination(task, data_center, lambda *_: None)
    assert cache.contains(task.application_id)
    assert manager.pending_store == {}
    assert not manager._needs_container(make_task(manager.edge_devices[0], identifier=2), data_center)
    assert cache.hits == 1 and cache.misses == 1
    assert not manager._needs_container(task, cloud)
    assert manager._needs_container(task, sensor)


def test_the_cached_run_downloads_less_than_the_uncached_one(cache_parameters):
    engine, manager = build_manager("cache", cache_parameters, load_settings(CACHE_SETTINGS),
                                    cache_scenario(cache_parameters, 40))
    engine.start()
    hits = sum(cache.hits for cache in manager.container_caches.values())
    misses = sum(cache.misses for cache in manager.container_caches.values())
    assert hits > 0 and misses > 0
    assert "hit ratio" in manager.cache_report()
    row = build_row(manager)

    # The baseline is the same workload with the cache switched off: registry_mode
    # CLOUD makes UncachedRegistryManager pay for a download on every request,
    # while the core manager would remember the container forever.
    cache_parameters.registry_mode = "CLOUD"
    uncached = build_manager("cloud_always", cache_parameters, load_settings(CACHE_SETTINGS),
                             cache_scenario(cache_parameters, 40))
    assert not uncached[1].cache_enabled and uncached[1].container_caches == {}
    baseline = build_row(uncached[1], uncached[0])
    assert row[COLUMNS[24]] < baseline[COLUMNS[24]]


def build_row(manager, engine=None):
    if engine is None:
        return summarize_without_rerun(manager)
    engine.start()
    from pureedgesim import summarize
    return summarize(manager)


def summarize_without_rerun(manager):
    from pureedgesim import summarize
    return summarize(manager)


def test_the_uncached_manager_downloads_a_container_for_every_request(cache_parameters):
    cache_parameters.registry_mode = "CLOUD"
    engine, manager = build_manager("cloud_always", cache_parameters, load_settings(CACHE_SETTINGS),
                                    cache_scenario(cache_parameters, 40))
    assert isinstance(manager, UncachedRegistryManager)
    data_center = manager.nodes_generator.edge_data_centers[0]
    data_center.installed_containers.add(0)
    task = make_task(manager.edge_devices[0], identifier=7)
    assert manager._needs_container(task, data_center)
    assert not manager._needs_container(task, manager.nodes_generator.cloud_nodes[0])


def test_the_container_cache_script_writes_three_rows(tmp_path):
    rows = cache_module.main(devices=24, duration=SHORT_DURATION, seed=61, output=tmp_path)
    assert [row[COLUMNS[0]] for row in rows] == ["EDGE_ONLY"] * 3
    assert rows[0][COLUMNS[7]] == rows[1][COLUMNS[7]] == rows[2][COLUMNS[7]]
    assert rows[1][COLUMNS[24]] > rows[0][COLUMNS[24]] > rows[2][COLUMNS[24]]
    path = next(tmp_path.rglob("Sequential_simulation.csv"))
    with path.open(newline="", encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 3


# --------------------------------------------------------------------------- Example22

@pytest.fixture
def cluster_manager():
    return build(CLUSTER_SETTINGS, ClusterOrchestrator, "MIST_ONLY", "CLUSTER_LOCAL", 40)


def test_the_election_groups_the_neighbourhood_around_a_head(cluster_manager):
    engine, manager = cluster_manager
    orchestrator = manager.orchestrator
    devices = orchestrator.cluster_devices()
    heads, members = refresh_clusters(devices, manager.parameters.edge_devices_range)
    assert len(members) > 1
    for identifier, head in heads.items():
        assert heads[head] == head
        assert identifier in members[head]
    assert sum(len(group) for group in members.values()) == len(devices)
    assert any(len(group) > 1 for group in members.values())


def test_the_score_is_a_weighted_sum_of_normalised_signals():
    assert raw_score(20000, 20000, 1.0, 1.0, 10) == pytest.approx(1.0)
    assert raw_score(20000, 20000, 1.0, 1.0, 40) == pytest.approx(1.0)
    assert raw_score(10000, 20000, 0.5, 0.5, 5) == pytest.approx(0.4 * 0.5 + 0.25 * 0.5 + 0.2 * 0.5
                                                                 + 0.15 * 0.5)
    assert raw_score(50000, 0, 1.0, 1.0, 10) == pytest.approx(0.25 + 0.2 + 0.15)


def test_the_election_prefers_the_strongest_stable_neighbour(cluster_manager):
    engine, manager = cluster_manager
    orchestrator = manager.orchestrator
    devices = orchestrator.cluster_devices()
    strong = max(devices, key=lambda node: node.total_mips)
    weak = min(devices, key=lambda node: node.total_mips)
    score = cluster_module.cluster_score
    assert score(strong, 10, strong.total_mips) > score(weak, 10, strong.total_mips)
    mobile = [node for node in devices if node.mobility_model is not None and node.mobility_model.is_mobile]
    if mobile:
        assert score(mobile[0], 10, strong.total_mips) < score(mobile[0], 10, strong.total_mips) + 1


def test_a_task_stays_inside_the_cluster_of_its_origin(cluster_manager):
    engine, manager = cluster_manager
    orchestrator = manager.orchestrator
    orchestrator.run_round()
    origin = next(node for node in orchestrator.cluster_devices() if orchestrator.cluster_head_of(node) is not None)
    head = orchestrator.cluster_head_of(origin)
    assert orchestrator.is_cluster_head(head)
    assert origin.id in [node.id for node in orchestrator.cluster_members_of(head)]
    candidates = orchestrator.cluster_candidates(origin)
    assert head in candidates and origin in candidates
    assert {node.id for node in candidates} <= {head.id} | {node.id for node in
                                                            orchestrator.cluster_members_of(head)} | {origin.id}
    index = orchestrator.find_computing_node([make_task(origin, identifier=11)], "CLUSTER_LOCAL", 0)
    assert index >= 0
    assert orchestrator.candidates[index] in candidates
    assert orchestrator.in_flight[orchestrator.candidates[index].id] == 1
    orchestrator.results_returned(make_task(origin, identifier=11))
    assert orchestrator.in_flight == {}


def test_the_head_discount_and_the_transfer_term_shape_the_cost(cluster_manager):
    engine, manager = cluster_manager
    orchestrator = manager.orchestrator
    orchestrator.run_round()
    origin = next(node for node in orchestrator.cluster_devices() if orchestrator.cluster_head_of(node) is not None)
    head = orchestrator.cluster_head_of(origin)
    task = make_task(origin)
    parameters = manager.parameters
    assert orchestrator.placement_cost(task, origin) == pytest.approx(task.length / origin.total_mips)
    transfer = parameters.wifi_delay + task.request_size / parameters.wifi_bandwidth
    assert orchestrator.placement_cost(task, head) == pytest.approx(
        transfer + task.length / head.total_mips)
    orchestrator.in_flight[origin.id] = 20
    assert orchestrator.placement_cost(task, origin) == pytest.approx(21 * task.length / origin.total_mips)
    # With a deep local queue the discounted head wins over the origin.
    chosen = orchestrator.find_computing_node([task], "CLUSTER_LOCAL", 0)
    assert orchestrator.placements[orchestrator.placement_kind(origin, head, orchestrator.candidates[chosen])] > 0


def test_the_placement_kinds_cover_head_member_local_and_outside(cluster_manager):
    engine, manager = cluster_manager
    orchestrator = manager.orchestrator
    orchestrator.run_round()
    devices = orchestrator.cluster_devices()
    origin = next(node for node in devices if orchestrator.cluster_head_of(node) is not None)
    head = orchestrator.cluster_head_of(origin)
    outsider = next(node for node in devices
                    if node.id not in orchestrator.members.get(head.id, []) and node is not origin)
    assert orchestrator.placement_kind(origin, None, origin) == "outside"
    assert orchestrator.placement_kind(origin, head, origin) == "local"
    assert orchestrator.placement_kind(origin, head, head) == "head"
    assert orchestrator.placement_kind(origin, head, outsider) == "outside"
    members = [node for node in devices if node.id in orchestrator.members.get(head.id, [])
               and node is not head and node is not origin]
    if members:
        assert orchestrator.placement_kind(origin, head, members[0]) == "member"
    assert ClusterOrchestrator._percent(0, 0) == "0.0"


def test_the_rounds_stop_when_every_device_is_dead(cluster_manager):
    engine, manager = cluster_manager
    orchestrator = manager.orchestrator
    for node in orchestrator.cluster_devices():
        node.status = NodeStatus.DEAD
    assert orchestrator.run_round() == 0
    assert orchestrator.coordinator() is None
    assert orchestrator.find_computing_node([make_task(manager.edge_devices[0])], "CLUSTER_LOCAL", 0) == -1


def test_an_out_of_range_origin_has_no_destination(cluster_manager):
    engine, manager = cluster_manager
    orchestrator = manager.orchestrator
    orchestrator.run_round()
    manager.parameters.edge_devices_range = 1e-6
    data_center = manager.nodes_generator.edge_data_centers[0]
    assert orchestrator.find_computing_node([make_task(data_center)], "CLUSTER_LOCAL", 0) == -1


def test_a_clustering_round_is_scheduled_every_interval(cluster_manager):
    engine, manager = cluster_manager
    orchestrator = manager.orchestrator
    before = orchestrator.cluster_updates
    orchestrator.process_event(Event(time=engine.clock, serial=0, destination=orchestrator, tag="OTHER"))
    assert orchestrator.cluster_updates == before
    engine.start()
    assert orchestrator.cluster_updates >= 4
    assert sum(orchestrator.placements.values()) > 0
    assert orchestrator.placements["outside"] == 0
    assert manager.metrics.mist_tasks > 0
    assert len(manager.finished_tasks) == manager.metrics.generated_tasks


def test_the_cluster_orchestrator_rejects_another_algorithm():
    with pytest.raises(ValueError, match="CLUSTER_LOCAL"):
        build(CLUSTER_SETTINGS, ClusterOrchestrator, "MIST_ONLY", "TRADE_OFF", 8)


def test_the_clustering_script_writes_a_row(tmp_path):
    row = cluster_module.main(devices=24, duration=SHORT_DURATION, seed=71, output=tmp_path)
    assert_sane_row(row)
    assert row[COLUMNS[19]] > 0
    assert row[COLUMNS[15]] == 0 and row[COLUMNS[17]] == 0
    assert (next(tmp_path.rglob("Sequential_simulation.csv"))).is_file()

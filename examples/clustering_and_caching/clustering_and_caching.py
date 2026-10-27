"""Cooperative container caching on self-clustered devices: two hooks working together.

    python examples/clustering_and_caching/clustering_and_caching.py

Port of the Java `Example7` (`Example7ClusteringDevice`, `Example7CachingDevice`
and `Example7CustomNetworkModel`), the cooperative caching algorithm of
Mechalikh, Taktak and Moussa, HPCS 2019. The Java example installs a custom
computing node that forms clusters and a custom network model that answers a
container request from a cluster replica instead of the remote registry. The
Python port reaches the same two extension points through the two hooks the
`Simulation` class now exposes, `set_custom_topology_creator` for the clustering
and `set_custom_network_model` for the caching, so nothing is subclassed that does
not have to be.

The clustering is done once, when the topology is built: every device is scored by
capacity, battery, stability and neighbourhood, points to the best neighbour it can
reach, and the devices that point to themselves become the cluster heads. Each
member gains a direct LAN link to its head and the heads are published to the
orchestrators list, so `deploy_orchestrator=CLUSTER` places the orchestrator on the
cluster heads. The caching lives in the network model: the core emits a "container
download" transfer whenever a destination still has to pull a container from the
registry, so the model intercepts that transfer, serves it from the head's replica
over the LAN when the cluster already holds the application, and only crosses the
WAN to the registry the first time, keeping that first copy at the head for the rest
of the cluster to reuse. `main` runs the cache against the same clustered topology
with the cooperative model switched off, and the difference is the WAN traffic the
sharing avoids. That is the synergy the example is built to show: the head only
holds a replica worth sharing because the tasks that need it stay in the cluster.

"""
from __future__ import annotations

import sys
from pathlib import Path

from pureedgesim import (COLUMNS, DefaultNetworkModel, DefaultTopologyCreator, Engine, LinkTechnology,
                         LinkType, Randomness, Scenario, Simulation, SimulationManager,
                         load_parameters, load_settings, run_scenario, summarize)

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/clustering_and_caching/output"

# A cluster head never keeps more than this many replicas of one application, the
# counterpart of Example7CustomNetworkModel.MAX_NUMBER_OF_REPLICAS.
MAX_REPLICAS = 8
# Weights of the head election: a capacity, battery, stability and neighbourhood
# blend normalised to the strongest device, the counterpart of
# Example7ClusteringDevice.getOriginalWeight.
CAPACITY_WEIGHT = 0.4
BATTERY_WEIGHT = 0.25
STABILITY_WEIGHT = 0.2
DEGREE_WEIGHT = 0.15
DEGREE_SATURATION = 10
STABILITY_REFERENCE_SPEED = 10.0


def cluster_score(device, neighbors: int, max_capacity: float) -> float:
    """The election score of a device, read from a live node."""
    battery = 1.0
    if device.energy_model.battery_powered:
        battery = max(0.0, min(1.0, device.get_remaining_battery_percentage() / 100.0))
    stability = 1.0
    mobility = device.mobility_model
    if mobility is not None and mobility.is_mobile:
        stability = max(0.0, min(1.0, 1.0 - mobility.speed / STABILITY_REFERENCE_SPEED))
    capacity = 0.0 if max_capacity <= 0 else min(1.0, device.total_mips / max_capacity)
    degree = min(1.0, neighbors / DEGREE_SATURATION)
    return (CAPACITY_WEIGHT * capacity + BATTERY_WEIGHT * battery
            + STABILITY_WEIGHT * stability + DEGREE_WEIGHT * degree)


def elect_heads(devices, range_: float) -> dict[int, int]:
    """Maps the identifier of every device to the head it follows.

    Each device points to the best scored neighbour within range, itself included,
    ties going to the lower identifier; following the pointers leads to a device
    that points to itself, which is the cluster head.
    """
    alive = [node for node in devices if not node.is_dead() and not node.is_sensor]
    max_capacity = max((node.total_mips for node in alive), default=0.0)
    best: dict[int, int] = {}
    for node in alive:
        neighbors = [other for other in alive if other is node or node.distance_to(other) <= range_]
        scores = {other.id: cluster_score(other, len(neighbors), max_capacity) for other in neighbors}
        best[node.id] = min(scores, key=lambda identifier: (-scores[identifier], identifier))
    heads: dict[int, int] = {}
    for identifier in best:
        current = identifier
        for _ in range(len(best) + 1):
            if best[current] == current:
                break
            current = best[current]
        heads[identifier] = current
    return heads


class ClusterTopologyCreator(DefaultTopologyCreator):
    """The default wiring plus a tree of links from every device to its cluster head."""

    def __init__(self, manager, generator, files) -> None:
        super().__init__(manager, generator, files)
        self.head_of: dict[int, int] = {}
        self.members: dict[int, list[int]] = {}
        self.cluster_links = 0

    def create(self) -> None:
        super().create()
        self._cluster()
        self._publish_heads()
        self._report()

    def _cluster(self) -> None:
        devices = [node for node in self.generator.edge_devices if not node.is_sensor]
        heads = elect_heads(devices, self.parameters.edge_devices_range)
        for identifier, head in heads.items():
            self.head_of[identifier] = head
            self.members.setdefault(head, []).append(identifier)
        # The network model and the test read the clusters through the manager.
        self.manager.cluster_head_of = self.head_of
        self.manager.cluster_members = self.members

    def _publish_heads(self) -> None:
        """Wire each member to its head and open the head to the orchestrators list."""
        bandwidth, delay = self.parameters.wifi_bandwidth, self.parameters.wifi_delay
        for member_id, head_id in self.head_of.items():
            if member_id == head_id:
                continue
            member = self._node(member_id)
            head = self._node(head_id)
            self.graph.connect(member, head, bandwidth, delay, 0.0, LinkType.LAN, LinkTechnology.WIFI)
            self.graph.connect(head, member, bandwidth, delay, 0.0, LinkType.LAN, LinkTechnology.WIFI)
            self.cluster_links += 2
        for head_id in self.members:
            head = self._node(head_id)
            head.is_orchestrator = True
            if head not in self.generator.orchestrators:
                self.generator.orchestrators.append(head)

    def _report(self) -> None:
        sizes = [len(group) for group in self.members.values()]
        average = sum(sizes) / len(sizes) if sizes else 0.0
        print(f"Clustering - {len(sizes)} cluster heads over {sum(sizes)} devices, "
              f"{self.cluster_links} tree links wired, average size {average:.1f}, "
              f"largest {max(sizes, default=0)}")

    def _node(self, identifier: int):
        return next(node for node in self.generator.edge_devices if node.id == identifier)


class CooperativeCacheNetworkModel(DefaultNetworkModel):
    """Serves a container download from the cluster head when it already has a replica.

    The manager calls `send` with a "container download" when the destination does
    not hold the application yet; the routing decision is exactly where the
    cooperative cache belongs, so a replica kept by the cluster head is pulled over
    the LAN and only a cold application crosses the WAN.
    """

    def __init__(self, manager) -> None:
        super().__init__(manager)
        # app id -> replica count, per cluster head, mirroring the Remotecache list
        # of Example7CachingDevice.
        self.replicas: dict[int, dict[int, int]] = {}
        self.served_from_cache = 0
        self.pulled_from_registry = 0
        self.cache_hits = 0

    def send(self, task, size: float, route, callback, description: str) -> None:
        if description == "container download" and self._cooperative_enabled():
            head = self._head_of(task.destination)
            cached = self.replicas.setdefault(head.id, {})
            count = cached.get(task.application_id, 0)
            if count > 0:
                if head is task.destination:
                    # The destination is the head and already keeps the replica: no hop.
                    self.cache_hits += 1
                    callback(task, None)
                    return
                # The cluster holds a replica, pull it from the head over the LAN.
                self.served_from_cache += 1
                cached[task.application_id] = min(count + 1, MAX_REPLICAS)
                super().send(task, size, self.route_for(head, task.destination), callback, description)
                return
            # Cold application: download once from the registry, over the WAN, and keep
            # the first copy at the head so the rest of the cluster reuses it.
            self.pulled_from_registry += 1
            cached[task.application_id] = 1
        super().send(task, size, route, callback, description)

    def _cooperative_enabled(self) -> bool:
        # The core only emits a "container download" transfer when the registry is
        # consulted per destination (registry_mode=CLOUD); CACHE short-circuits the
        # whole download. So the cooperative cache intercepts the CLOUD path, which
        # is the "pull from the registry" strategy the HPCS paper compares against.
        return self.parameters.enable_registry and hasattr(self.manager, "cluster_head_of")

    def _head_of(self, node):
        head_id = self.manager.cluster_head_of.get(node.id)
        if head_id is None:
            return node
        return next((other for other in self.manager.edge_devices if other.id == head_id), node)

    def cache_report(self) -> str:
        total = self.served_from_cache + self.pulled_from_registry
        ratio = 100.0 * self.served_from_cache / total if total else 0.0
        replicas = sum(len(cached) for cached in self.replicas.values())
        return (f"cooperative cache: {self.pulled_from_registry} WAN pulls, {self.served_from_cache} "
                f"cluster pulls ({ratio:.1f} % served locally), {self.cache_hits} head hits, "
                f"{replicas} distinct replicas over {len(self.replicas)} heads")

    def on_simulation_end(self) -> None:
        if self._cooperative_enabled():
            print(f"CooperativeCache - {self.cache_report()}")


def load_example_parameters(devices: int | None = None, duration: float | None = None,
                            seed: int | None = None):
    """The Example7 settings, shrunk and pinned to CLOUD so downloads reach the cache.

    registry_mode is forced to CLOUD: that is the path on which the core emits the
    container downloads the cooperative cache intercepts (CACHE short-circuits them).
    """
    result = load_parameters(SETTINGS / "simulation_parameters.properties")
    result.registry_mode = "CLOUD"
    if devices is not None:
        result.min_number_of_devices = result.max_number_of_devices = devices
        result.devices_increment = 1
    if duration is not None:
        result.simulation_duration = duration
    if seed is not None:
        result.random_seed = seed
    return result


def build(devices: int | None = None, duration: float | None = None, seed: int | None = None,
          output: str | Path = OUTPUT, cache: bool = True) -> Simulation:
    """A Simulation carrying the two Example7 extension points, registered the Java way.

    The topology creator always clusters; the cooperative network model is the
    caching hook, registered only when `cache` is true. With `cache=False` the same
    clustered topology keeps the plain registry pulls, the baseline the savings are
    measured against.
    """
    simulation = Simulation(SETTINGS, output, load_example_parameters(devices, duration, seed),
                            load_settings(SETTINGS))
    simulation.set_custom_topology_creator(ClusterTopologyCreator)
    if cache:
        simulation.set_custom_network_model(CooperativeCacheNetworkModel)
    return simulation


def build_manager(cache: bool, parameters, files, scenario) -> tuple:
    """An un-run engine and manager with the two Example7 hooks wired onto the manager.

    The manager kwargs are the same two models `set_custom_topology_creator` and
    `set_custom_network_model` feed through `run_scenario`, so the clustering and the
    cooperative cache can be inspected directly, the way the test checks the head
    election and the served-from-cache count.
    """
    Randomness.set_seed(parameters.random_seed)
    Randomness.begin_scenario(0)
    engine = Engine(parameters.simulation_duration)
    manager = SimulationManager(engine, parameters, files, scenario,
                                custom_topology_creator=ClusterTopologyCreator,
                                custom_network_model=CooperativeCacheNetworkModel if cache else None)
    manager.start_simulation()
    return engine, manager


def key_metrics(label: str, row: dict) -> str:
    return (f"{label:<18} tasks={row[COLUMNS[7]]:>7} ok={row[COLUMNS[8]]:>7} "
            f"wan_usage={row[COLUMNS[22]]:<11} container_wan={row[COLUMNS[25]]:<10} "
            f"container_lan={row[COLUMNS[26]]:<9} traffic_MB={row[COLUMNS[24]]:<9} "
            f"avg_delay={row[COLUMNS[4]]:<8} energy={row[COLUMNS[32]]}")


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> dict:
    """Runs the cooperative caching on the clustered topology, then the same clusters
    with the cooperative model switched off, and appends both rows to one CSV.

    The default settings ship the 300-device, 60-minute run of the Java example; the
    arguments shrink it for a quick check. The comparison is the WAN traffic the
    cooperative cache moves to the LAN.
    """
    seed = seed if seed is not None else 11
    cooperative = build(devices, duration, seed, output, cache=True)
    row = cooperative.launch()[0]
    print(key_metrics("CACHE cluster", row))
    # Same clustering, same workload, no cooperative model: every destination pays
    # the registry, over the WAN, for the containers it does not hold yet, the
    # cloud-registry strategy the paper measures against. The row goes into the CSV
    # the cooperative run just wrote, so the two scenarios sit side by side.
    baseline = build(devices, duration, seed, output, cache=False)
    parameters = baseline.parameters
    scenario = Scenario(parameters.orchestration_architectures[0], parameters.orchestration_algorithms[0],
                        parameters.max_number_of_devices)
    plain = run_scenario(parameters, baseline.files, scenario, 0,
                         custom_models={"topology_creator": ClusterTopologyCreator})
    _append_row(cooperative.results_folder, plain)
    print(key_metrics("CLOUD cluster", plain))
    saved = plain[COLUMNS[22]] - row[COLUMNS[22]]
    print(f"saving - WAN usage: {saved:.4f} s avoided out of {plain[COLUMNS[22]]:.4f} s "
          f"in the registry run")
    return row


def _append_row(folder: Path, row: dict) -> None:
    import csv

    path = folder / "Sequential_simulation.csv"
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    # A device count, a duration and a seed shrink the scenario for a quick check.
    kwargs = {}
    if len(sys.argv) > 1:
        kwargs["devices"] = int(sys.argv[1])
    if len(sys.argv) > 2:
        kwargs["duration"] = float(sys.argv[2])
    if len(sys.argv) > 3:
        kwargs["seed"] = int(sys.argv[3])
    main(**kwargs)

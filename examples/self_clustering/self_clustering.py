"""Devices that cluster themselves: an elected head per neighbourhood.

    python examples/self_clustering/self_clustering.py

Port of the Java `Example22SelfClusteringDevice` and `Example22ClusterOrchestrator`.
Each device scores itself from four local signals (capacity, battery, stability,
neighbourhood), points to the best neighbour it can reach, and the clusters
emerge from those pointers: a device that points to itself is a head, every
other device follows the pointers until it reaches one. The orchestrator then
places a task inside the cluster its origin joined, with a 25 percent discount
for the head.

The Python core has no hook for a custom computing node, so the election state
does not live on the devices. It lives in the orchestrator, which is registered
as a simulation entity and runs one clustering round every
`CLUSTER_UPDATE_INTERVAL` seconds instead of letting one coordinator device do
it. `elect_clusters` and `refresh_clusters` stay module level pure functions, the
counterpart of the two static methods of the Java device class.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from pureedgesim import COLUMNS, NodeType, Orchestrator, SimEntity, Simulation, load_parameters, load_settings

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/self_clustering/output"
ALGORITHM = "CLUSTER_LOCAL"

UPDATE_CLUSTERS = "UPDATE_CLUSTERS"
# Seconds between two clustering rounds, and the delay of the first one.
CLUSTER_UPDATE_INTERVAL = 30.0
FIRST_CLUSTERING_ROUND = 1.0

# Weights of the election score, all normalised between 0 and 1.
CAPACITY_WEIGHT = 0.4
BATTERY_WEIGHT = 0.25
STABILITY_WEIGHT = 0.2
DEGREE_WEIGHT = 0.15
DEGREE_SATURATION = 10
STABILITY_REFERENCE_SPEED = 10.0
# The head aggregates the load of its cluster, so it is cheaper than a member.
HEAD_COST_FACTOR = 0.75
PLACEMENT_KINDS = ("head", "member", "local", "outside")


def raw_score(capacity: float, max_capacity: float, battery: float, stability: float, neighbors: int) -> float:
    """The election score of a device from normalised inputs, for inspection and tests."""
    capacity_norm = 0.0 if max_capacity <= 0 else min(1.0, capacity / max_capacity)
    degree_norm = min(1.0, neighbors / DEGREE_SATURATION)
    return (CAPACITY_WEIGHT * capacity_norm + BATTERY_WEIGHT * battery + STABILITY_WEIGHT * stability
            + DEGREE_WEIGHT * degree_norm)


def cluster_score(device, neighbors: int, max_capacity: float) -> float:
    """The election score read from a live device."""
    battery = 1.0
    if device.energy_model.battery_powered:
        battery = max(0.0, min(1.0, device.get_remaining_battery_percentage() / 100.0))
    stability = 1.0
    mobility = device.mobility_model
    if mobility is not None and mobility.is_mobile:
        stability = max(0.0, min(1.0, 1.0 - mobility.speed / STABILITY_REFERENCE_SPEED))
    return raw_score(device.total_mips, max_capacity, battery, stability, neighbors)


def elect_clusters(devices, range_: float) -> dict[int, int]:
    """Maps the identifier of every eligible device to the head it follows.

    Each device points to the best scored node within range, itself included, and
    ties go to the lower identifier; following the pointers leads to a device that
    points to itself, which is the cluster head.
    """
    candidates = [node for node in devices if not node.is_dead() and not node.is_sensor]
    max_capacity = max((node.total_mips for node in candidates), default=0.0)
    best: dict[int, int] = {}
    for node in candidates:
        neighbors = [other for other in candidates if other is node or node.distance_to(other) <= range_]
        scores = {other.id: cluster_score(other, len(neighbors), max_capacity) for other in neighbors}
        # The highest score wins, the lower identifier breaks a tie, exactly like
        # the Java comparison of a strictly better score or an equal one.
        best[node.id] = min(scores, key=lambda node_id: (-scores[node_id], node_id))
    heads: dict[int, int] = {}
    for identifier in best:
        current = identifier
        for _ in range(len(best) + 1):
            if best[current] == current:
                break
            current = best[current]
        heads[identifier] = current
    return heads


def refresh_clusters(devices, range_: float) -> tuple[dict[int, int], dict[int, list[int]]]:
    """Runs the election and groups the members under the head they reached."""
    heads = elect_clusters(devices, range_)
    members: dict[int, list[int]] = {}
    for identifier, head in heads.items():
        members.setdefault(head, []).append(identifier)
    return heads, members


class ClusterOrchestrator(SimEntity, Orchestrator):
    """Places each task inside the cluster of the device that generated it."""

    def __init__(self, manager) -> None:
        SimEntity.__init__(self, manager.engine)
        Orchestrator.__init__(self, manager)
        algorithm = manager.scenario.orchestration_algorithm
        if algorithm != ALGORITHM:
            raise ValueError(f"{type(self).__name__} - unknown orchestration algorithm {algorithm!r}, "
                             f"expected {ALGORITHM}.")
        self.nodes_by_id = {node.id: node for node in manager.computing_nodes}
        self.index_of: dict[int, int] = {}
        self.in_flight: dict[int, int] = {}
        self.decisions: dict[int, int] = {}
        self.head_of: dict[int, int] = {}
        self.members: dict[int, list[int]] = {}
        self.cluster_updates = 0
        self.placements: Counter = Counter()

    def initialize(self, architecture: str) -> None:
        super().initialize(architecture)
        self.index_of = {node.id: index for index, node in enumerate(self.candidates)}

    def on_simulation_start(self) -> None:
        self.schedule(self, FIRST_CLUSTERING_ROUND, UPDATE_CLUSTERS)

    def process_event(self, event) -> None:
        if event.tag != UPDATE_CLUSTERS:
            return
        self.run_round()
        if self.engine.clock < self.manager.parameters.simulation_duration:
            self.schedule(self, CLUSTER_UPDATE_INTERVAL, UPDATE_CLUSTERS)

    def cluster_devices(self) -> list:
        """The mist nodes that may join a cluster: sensors are already excluded."""
        return [node for node in self.candidates if node.type is NodeType.EDGE_DEVICE]

    def coordinator(self):
        """The first alive device, the counterpart of the Java round coordinator."""
        for device in self.cluster_devices():
            if not device.is_dead():
                return device
        return None

    def run_round(self) -> int:
        """Refreshes the clusters unless every device is dead; returns the alive count."""
        devices = self.cluster_devices()
        alive = [device for device in devices if not device.is_dead()]
        if not alive:
            return 0
        self.head_of, self.members = refresh_clusters(devices, self.manager.parameters.edge_devices_range)
        self.cluster_updates += 1
        return len(alive)

    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int:
        task = tasks[0]
        origin = task.source_device
        head = self.cluster_head_of(origin)
        best, best_cost = -1, float("inf")
        for node in self.cluster_candidates(origin):
            index = self.index_of.get(node.id, -1)
            if index < 0 or not self.offloading_is_possible(node, task):
                continue
            cost = self.placement_cost(task, node)
            if head is not None and node is head:
                cost *= HEAD_COST_FACTOR
            if cost < best_cost:
                best, best_cost = index, cost
        if best >= 0:
            chosen = self.candidates[best]
            self.history[best] += 1
            self.in_flight[chosen.id] = self.in_flight.get(chosen.id, 0) + 1
            self.decisions[task.id] = chosen.id
            self.placements[self.placement_kind(origin, head, chosen)] += 1
        return best

    def results_returned(self, task) -> None:
        identifier = self.decisions.pop(task.id, None)
        if identifier is None:
            return
        pending = self.in_flight.get(identifier, 0)
        if pending <= 1:
            self.in_flight.pop(identifier, None)
        else:
            self.in_flight[identifier] = pending - 1

    def cluster_candidates(self, origin) -> list:
        """Head, members of its cluster and the origin; all candidates when headless."""
        head = self.cluster_head_of(origin)
        if head is None:
            candidates = list(self.candidates)
        else:
            members = [self.nodes_by_id[identifier] for identifier in self.members.get(head.id, [])
                       if identifier in self.nodes_by_id]
            candidates = [head] + [node for node in members if node is not head]
        if origin not in candidates:
            candidates.append(origin)
        return candidates

    def placement_cost(self, task, node) -> float:
        """Queueing plus execution on the node, plus the radio time when it is remote."""
        capacity = max(1.0, node.total_mips)
        pending = self.in_flight.get(node.id, 0)
        compute = (1 + pending) * task.length / capacity
        if node is task.source_device:
            return compute
        parameters = self.manager.parameters
        transfer = parameters.wifi_delay + task.request_size / max(1.0, parameters.wifi_bandwidth)
        return transfer + compute

    def placement_kind(self, origin, head, chosen) -> str:
        if head is None:
            return "outside"
        if chosen is origin:
            return "local"
        if chosen is head:
            return "head"
        if chosen.id in self.members.get(head.id, []):
            return "member"
        return "outside"

    def cluster_head_of(self, node):
        identifier = self.head_of.get(node.id)
        return self.nodes_by_id.get(identifier) if identifier is not None else None

    def is_cluster_head(self, node) -> bool:
        return self.head_of.get(node.id) == node.id

    def cluster_members_of(self, node) -> list:
        return [self.nodes_by_id[identifier] for identifier in self.members.get(node.id, [])
                if identifier in self.nodes_by_id]

    def on_simulation_end(self) -> None:
        total = sum(self.placements.values())
        shares = ", ".join(f"{kind}={self._percent(self.placements[kind], total)} %" for kind in PLACEMENT_KINDS)
        sizes = [len(members) for members in self.members.values()]
        alive = sum(1 for device in self.cluster_devices() if not device.is_dead())
        average = sum(sizes) / len(sizes) if sizes else 0.0
        print(f"ClusterOrchestrator - cluster placement: {total} placements, {shares}")
        print(f"ClusterOrchestrator - clustering: {len(sizes)} clusters over {alive} devices, "
              f"{self.cluster_updates} rounds, average size {average:.1f}, largest {max(sizes, default=0)}")

    @staticmethod
    def _percent(count: int, total: int) -> str:
        return f"{100.0 * count / total:.1f}" if total else "0.0"


def run(label: str = "CLUSTER_LOCAL", devices: int | None = None, duration: float | None = None,
        seed: int | None = None, output: str | Path = OUTPUT) -> dict:
    """One full scenario; the optional arguments shrink it for a quick check."""
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    if devices is not None:
        parameters.min_number_of_devices = parameters.max_number_of_devices = devices
        parameters.devices_increment = 1
    if duration is not None:
        parameters.simulation_duration = duration
    if seed is not None:
        parameters.random_seed = seed
    simulation = Simulation(SETTINGS, output, parameters, load_settings(SETTINGS))
    simulation.set_custom_orchestrator(ClusterOrchestrator)
    row = simulation.launch()[0]
    print(f"{label:<16} devices={row[COLUMNS[2]]:>4} tasks={row[COLUMNS[7]]:>6} ok={row[COLUMNS[8]]:>6} "
          f"failed(delay)={row[COLUMNS[10]]:>5} avg_delay={row[COLUMNS[4]]:<8} "
          f"cloud={row[COLUMNS[15]]:>4} edge={row[COLUMNS[17]]:>4} mist={row[COLUMNS[19]]:>5} "
          f"lan_usage={row[COLUMNS[23]]:<9} traffic_MB={row[COLUMNS[24]]:<9} energy={row[COLUMNS[32]]}")
    return row


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> dict:
    """Runs the clustering scenario; the arguments shrink it for a quick check."""
    return run("CLUSTER_LOCAL", devices, duration, seed, output)


if __name__ == "__main__":
    main()

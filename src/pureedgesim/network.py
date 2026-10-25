"""Links, routing and progressive transfers, the counterpart of the network package."""
from __future__ import annotations

import heapq
from enum import Enum

from .engine import Event, SimEntity
from .nodes import RECEPTION, TRANSMISSION, ComputingNode, EventType, NodeType
from .parameters import SimulationParameters


class LinkType(Enum):
    WAN = "WAN"
    MAN = "MAN"
    LAN = "LAN"


class LinkTechnology(Enum):
    WIFI = "wifi"
    CELLULAR = "cellular"
    ETHERNET = "ethernet"


class NetworkLink:
    """A directional link that shares its bandwidth equally among active transfers."""

    def __init__(self, source: ComputingNode, destination: ComputingNode, bandwidth: float, delay: float,
                 energy_per_bit: float, link_type: LinkType, technology: LinkTechnology = LinkTechnology.ETHERNET,
                 ignore_energy: bool = False) -> None:
        self.source = source
        self.destination = destination
        self.bandwidth = bandwidth
        self.delay = delay
        self.energy_per_bit = energy_per_bit
        self.type = link_type
        self.technology = technology
        self.ignore_energy = ignore_energy
        self.transfers: list["TransferProgress"] = []
        self.total_transferred_data = 0.0
        self.total_usage_time = 0.0
        self.total_energy_consumption = 0.0

    @property
    def name(self) -> str:
        return f"{self.source.name} -> {self.destination.name} ({self.type.value})"

    def add_transfer(self, progress: "TransferProgress") -> None:
        self.transfers.append(progress)

    def remove_transfer(self, progress: "TransferProgress") -> None:
        if progress in self.transfers:
            self.transfers.remove(progress)

    def allocated_bandwidth(self) -> float:
        if not self.transfers:
            return self.bandwidth
        return self.bandwidth / len(self.transfers)

    def update(self, elapsed: float, realistic: bool) -> list["TransferProgress"]:
        """Advances every transfer and returns the ones that finished."""
        if not self.transfers:
            return []
        bandwidth = self.allocated_bandwidth()
        finished: list[TransferProgress] = []
        for progress in list(self.transfers):
            bits = progress.remaining_size
            if realistic:
                bits = min(elapsed * bandwidth, bits)
            delay = bits / bandwidth
            progress.remaining_size -= bits
            progress.transferred_bits += bits
            progress.elapsed_time += delay
            progress.bandwidth_samples.append(bandwidth)
            self.total_usage_time += delay
            self.total_transferred_data += bits
            if progress.remaining_size <= 0:
                progress.remaining_size = 0.0
                self.remove_transfer(progress)
                finished.append(progress)
        return finished


class TransferProgress:
    def __init__(self, task, size: float, route: list[NetworkLink], callback, description: str) -> None:
        self.task = task
        self.route = route
        self.hop_index = 0
        self.link = route[0]
        self.remaining_size = float(size)
        self.total_size = float(size)
        self.transferred_bits = 0.0
        self.elapsed_time = 0.0
        self.hop_times: list[float] = []
        self.bandwidth_samples: list[float] = []
        self.callback = callback
        self.description = description


class InfrastructureGraph:
    """Directed graph with latency weighted shortest paths, cached per pair."""

    def __init__(self) -> None:
        self.links: list[NetworkLink] = []
        self.adjacency: dict[int, list[tuple[int, NetworkLink]]] = {}
        self.nodes_by_id: dict[int, ComputingNode] = {}
        self._cache: dict[tuple[int, int], list[NetworkLink]] = {}

    def add_node(self, node: ComputingNode) -> None:
        self.nodes_by_id.setdefault(node.id, node)
        self.adjacency.setdefault(node.id, [])

    def connect(self, source: ComputingNode, destination: ComputingNode, bandwidth: float, delay: float,
                energy_per_bit: float, link_type: LinkType,
                technology: LinkTechnology = LinkTechnology.ETHERNET) -> NetworkLink:
        self.add_node(source)
        self.add_node(destination)
        link = NetworkLink(source, destination, bandwidth, delay, energy_per_bit, link_type, technology)
        self.links.append(link)
        self.adjacency[source.id].append((destination.id, link))
        self._cache.clear()
        return link

    def shortest_path(self, source: ComputingNode, destination: ComputingNode) -> list[NetworkLink]:
        key = (source.id, destination.id)
        if key in self._cache:
            return self._cache[key]
        path = self._dijkstra(source, destination)
        self._cache[key] = path
        return path

    def path_delay(self, source: ComputingNode, destination: ComputingNode) -> float:
        return sum(link.delay for link in self.shortest_path(source, destination))

    def _dijkstra(self, source: ComputingNode, destination: ComputingNode) -> list[NetworkLink]:
        best_delay = {source.id: 0.0}
        previous: dict[int, tuple[int, NetworkLink]] = {}
        visited: set[int] = set()
        heap = [(0.0, source.id)]
        while heap:
            delay, node_id = heapq.heappop(heap)
            if node_id in visited:
                continue
            visited.add(node_id)
            if node_id == destination.id:
                break
            for neighbour, link in self.adjacency.get(node_id, []):
                # Edge devices are only reachable through their own access link,
                # never as intermediate hops, so mobility cannot open shortcuts.
                neighbour_node = self.nodes_by_id.get(neighbour)
                if (neighbour_node is not None and neighbour_node.type == NodeType.EDGE_DEVICE
                        and neighbour != destination.id):
                    continue
                candidate = delay + link.delay
                if candidate < best_delay.get(neighbour, float("inf")):
                    best_delay[neighbour] = candidate
                    previous[neighbour] = (node_id, link)
                    heapq.heappush(heap, (candidate, neighbour))
        if destination.id not in visited:
            return []
        path: list[NetworkLink] = []
        cursor = destination.id
        while cursor != source.id:
            parent, link = previous[cursor]
            path.append(link)
            cursor = parent
        return list(reversed(path))


class DefaultNetworkModel(SimEntity):
    """Routes transfers, shares bandwidth, charges link and device energy."""

    def __init__(self, manager) -> None:
        super().__init__(manager.engine)
        self.manager = manager
        self.parameters: SimulationParameters = manager.parameters
        self.graph = InfrastructureGraph()
        self.active_transfers: set[TransferProgress] = set()
        self.network_usage = {LinkType.WAN: 0.0, LinkType.MAN: 0.0, LinkType.LAN: 0.0}
        self.technology_usage = {LinkTechnology.WIFI: 0.0, LinkTechnology.CELLULAR: 0.0,
                                 LinkTechnology.ETHERNET: 0.0}
        self.link_energy = {LinkType.WAN: 0.0, LinkType.MAN: 0.0, LinkType.LAN: 0.0}
        self.technology_energy = {LinkTechnology.WIFI: 0.0, LinkTechnology.CELLULAR: 0.0,
                                  LinkTechnology.ETHERNET: 0.0}
        self.total_bandwidth_samples: list[float] = []
        self.total_traffic_bits = 0.0
        self.container_usage = {LinkType.WAN: 0.0, LinkType.MAN: 0.0, LinkType.LAN: 0.0}

    def process_event(self, event: Event) -> None:
        if event.tag == EventType.UPDATE_NETWORK:
            self.update()
            if self.active_transfers:
                self.schedule(self, self.parameters.network_update_interval, EventType.UPDATE_NETWORK)

    def send(self, task, size: float, route: list[NetworkLink], callback, description: str) -> None:
        if not route:
            callback(task, None)
            return
        task.total_network_time += sum(link.delay for link in route)
        progress = TransferProgress(task, size, route, callback, description)
        task.network_hops.append(progress)
        self._activate(progress)

    def _activate(self, progress: TransferProgress) -> None:
        progress.link.add_transfer(progress)
        self.active_transfers.add(progress)
        if len(self.active_transfers) == 1:
            self.schedule(self, self.parameters.network_update_interval, EventType.UPDATE_NETWORK)

    def update(self) -> None:
        elapsed = self.parameters.network_update_interval
        realistic = self.parameters.realistic_network_model
        completed: list[TransferProgress] = []
        for link in list(self.graph.links):
            for progress in link.update(elapsed, realistic):
                progress.hop_times.append(progress.elapsed_time)
                # Charging must happen before the hop counters are reset, otherwise
                # the usage and the energy of the hop are lost.
                self._charge(progress)
                progress.elapsed_time = 0.0
                progress.transferred_bits = 0.0
                progress.bandwidth_samples.clear()
                if progress.hop_index + 1 < len(progress.route):
                    progress.hop_index += 1
                    progress.link = progress.route[progress.hop_index]
                    progress.remaining_size = progress.total_size
                    self._activate(progress)
                else:
                    self.active_transfers.discard(progress)
                    self.total_traffic_bits += progress.total_size
                    completed.append(progress)
        for progress in completed:
            progress.callback(progress.task, progress)

    def _charge(self, progress: TransferProgress) -> None:
        """Books the hop just finished: usage, traffic, energy."""
        link = progress.link
        task = progress.task
        task.total_network_time += progress.elapsed_time
        self.network_usage[link.type] += progress.elapsed_time
        self.technology_usage[link.technology] += progress.elapsed_time
        if progress.description == "container download":
            self.container_usage[link.type] += progress.elapsed_time
        self.total_bandwidth_samples.extend(progress.bandwidth_samples)
        if not link.ignore_energy:
            energy = progress.transferred_bits * link.energy_per_bit
            link.total_energy_consumption += energy
            self.link_energy[link.type] += energy
            self.technology_energy[link.technology] += energy
        for node, flag in ((link.source, TRANSMISSION), (link.destination, RECEPTION)):
            if node is not None and node.type == NodeType.EDGE_DEVICE:
                node.energy_model.update_wireless_energy_consumption(progress.transferred_bits, flag)

    def route_for(self, source: ComputingNode, destination: ComputingNode) -> list[NetworkLink]:
        """The four routing cases of the default network model."""
        if source is destination:
            return []
        if source.type == NodeType.EDGE_DEVICE and destination.type == NodeType.EDGE_DEVICE:
            return self.manager.device_to_device_route(source, destination)
        if source.type == NodeType.EDGE_DEVICE:
            access = source.up_link if destination is source.serving_edge_data_center else source.wan_up_link
            if access is None:
                return []
            if access.destination is destination:
                return [access]
            return [access, *self.graph.shortest_path(access.destination, destination)]
        if destination.type == NodeType.EDGE_DEVICE:
            access = destination.down_link if source is destination.serving_edge_data_center \
                else destination.wan_down_link
            if access is None:
                return []
            if access.source is source:
                return [access]
            return [*self.graph.shortest_path(source, access.source), access]
        return self.graph.shortest_path(source, destination)

    def path_delay(self, source: ComputingNode, destination: ComputingNode) -> float:
        return self.graph.path_delay(source, destination)

    def get_average_bandwidth_per_task(self) -> float:
        if not self.total_bandwidth_samples:
            return 0.0
        return sum(self.total_bandwidth_samples) / len(self.total_bandwidth_samples) / 1e6

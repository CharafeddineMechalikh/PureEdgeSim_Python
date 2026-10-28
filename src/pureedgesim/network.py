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
    IGNORE = "IGNORE"


class LinkTechnology(Enum):
    WIFI = "wifi"
    CELLULAR = "cellular"
    ETHERNET = "ethernet"


class NetworkLink:
    """A directional link that shares its bandwidth equally among active transfers.

    The technology is the radio of an access link, or None for an infrastructure
    link, which no radio category counts. An IGNORE link carries traffic but
    appears in no usage or energy metric, so that the last hop of the shared WAN
    is not booked twice on top of the device link that already paid for it.
    """

    def __init__(self, source: ComputingNode, destination: ComputingNode, bandwidth: float, delay: float,
                 energy_per_bit: float, link_type: LinkType,
                 technology: LinkTechnology | None = None) -> None:
        self.source = source
        self.destination = destination
        self.bandwidth = bandwidth
        self.delay = delay
        self.energy_per_bit = energy_per_bit
        self.type = link_type
        self.technology = technology
        self.transfers: list["TransferProgress"] = []
        self.total_transferred_data = 0.0
        self.total_usage_time = 0.0
        self.total_energy_consumption = 0.0
        self.scheduled = False

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
                energy_per_bit: float, link_type: LinkType, technology: LinkTechnology | None = None) -> NetworkLink:
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

    def move(self, link: NetworkLink, source: ComputingNode, destination: ComputingNode) -> None:
        """Points an existing link at another pair of nodes, like setDst and setSrc do in Java.

        A moving device keeps one access link whose far end follows the closest data
        center, so the graph never accumulates stale links behind it.
        """
        self.adjacency[link.source.id].remove((link.destination.id, link))
        self.add_node(source)
        self.add_node(destination)
        link.source = source
        link.destination = destination
        self.adjacency.setdefault(source.id, []).append((destination.id, link))
        self._cache.clear()

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
            self._update_link(event.data)
        elif event.tag == EventType.TRANSFER_FINISHED:
            self._arrive(event.data)

    def send(self, task, size: float, route: list[NetworkLink], callback, description: str) -> None:
        if not route:
            callback(task, None)
            return
        task.total_network_time += sum(link.delay for link in route)
        progress = TransferProgress(task, size, route, callback, description)
        task.network_hops.append(progress)
        self._activate(progress)

    def _activate(self, progress: TransferProgress) -> None:
        """Queues a transfer on its current link and wakes that link up."""
        link = progress.link
        link.add_transfer(progress)
        self.active_transfers.add(progress)
        if link.scheduled:
            return
        link.scheduled = True
        # The static model serves the hop at the current clock, like the Java link,
        # which is woken up with scheduleNow. The realistic one waits for the next
        # poll, so a transfer that joins late is served with the others.
        if self.parameters.realistic_network_model:
            self.schedule(self, self.parameters.network_update_interval, EventType.UPDATE_NETWORK, link)
        else:
            self.schedule_now(self, EventType.UPDATE_NETWORK, link)

    def _update_link(self, link: NetworkLink) -> None:
        """Serves every transfer queued on one link, the counterpart of updateTransfersProgress."""
        link.scheduled = False
        for progress in link.update(self.parameters.network_update_interval,
                                    self.parameters.realistic_network_model):
            self._hop_finished(progress)
        if link.transfers:
            # Only the realistic model leaves a transfer behind; the static one
            # clears the whole payload in one step, so the link goes idle.
            self.schedule(self, self.parameters.network_update_interval, EventType.UPDATE_NETWORK, link)
            link.scheduled = True

    def _hop_finished(self, progress: TransferProgress) -> None:
        """Books the hop just finished and forwards the transfer to the next link."""
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
            self.schedule(self, progress.link.delay, EventType.TRANSFER_FINISHED, progress)

    def _arrive(self, progress: TransferProgress) -> None:
        """The data reached its destination: carry on with the workflow it belongs to."""
        self.total_traffic_bits += progress.total_size
        progress.callback(progress.task, progress)

    def _charge(self, progress: TransferProgress) -> None:
        """Books the hop just finished: usage, traffic, energy."""
        link = progress.link
        task = progress.task
        task.total_network_time += progress.elapsed_time
        self.total_bandwidth_samples.extend(progress.bandwidth_samples)
        if link.type == LinkType.IGNORE:
            # The hop still delays the task, but Java gives it no metric bucket: its
            # traffic was already counted on the device link that entered the WAN.
            return
        self.network_usage[link.type] += progress.elapsed_time
        if link.technology is not None:
            self.technology_usage[link.technology] += progress.elapsed_time
        if progress.description == "container download":
            self.container_usage[link.type] += progress.elapsed_time
        energy = progress.transferred_bits * link.energy_per_bit
        link.total_energy_consumption += energy
        self.link_energy[link.type] += energy
        if link.technology is not None:
            self.technology_energy[link.technology] += energy
        for node, flag in ((link.source, TRANSMISSION), (link.destination, RECEPTION)):
            if node is not None and node.type == NodeType.EDGE_DEVICE:
                node.energy_model.update_wireless_energy_consumption(progress.transferred_bits, flag)

    def route_for(self, source: ComputingNode, destination: ComputingNode) -> list[NetworkLink]:
        """The four routing cases of the default network model.

        A device reaching an edge data center always starts on its own access link, and
        an edge data center reaching a device ends on that access link. Any other pair
        follows the shortest path, which may start on the access or on the WAN link.
        """
        if source is destination:
            return []
        if source.type == NodeType.EDGE_DEVICE and destination.type == NodeType.EDGE_DEVICE:
            return self.manager.device_to_device_route(source, destination)
        if source.type == NodeType.EDGE_DEVICE and destination.type == NodeType.EDGE_DATACENTER:
            access = source.up_link or source.wan_up_link
            if access is None or access.destination is destination:
                return [access] if access is not None else []
            return [access, *self.graph.shortest_path(access.destination, destination)]
        if source.type == NodeType.EDGE_DATACENTER and destination.type == NodeType.EDGE_DEVICE:
            access = destination.down_link or destination.wan_down_link
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

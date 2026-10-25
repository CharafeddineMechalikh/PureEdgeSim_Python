"""Creates computing nodes and the default topology."""
from __future__ import annotations

from .config import DatacenterSpec, DeviceSpec, ScenarioFiles
from .mobility import Location, MobilityModel, MobilityModelFactory, ReferencePointGroupMobilityModel
from .network import LinkTechnology, LinkType, NetworkLink
from .nodes import (CloudDataCenter, ComputingNode, EdgeDataCenter, EdgeDevice, NodeType, Router)


class ComputingNodesGenerator:
    def __init__(self, manager) -> None:
        self.manager = manager
        self.parameters = manager.parameters
        self.random = manager.random
        self.cloud_nodes: list[ComputingNode] = []
        self.edge_data_centers: list[ComputingNode] = []
        self.edge_devices: list[ComputingNode] = []
        self.orchestrators: list[ComputingNode] = []
        self.routers: list[ComputingNode] = []

    def generate(self, files: ScenarioFiles, device_count: int) -> None:
        for spec in files.cloud:
            self.cloud_nodes.append(self._create_datacenter(spec, CloudDataCenter(self.manager, 1, 1, 1, 1)))
        for spec in files.edge_datacenters:
            self.edge_data_centers.append(self._create_datacenter(spec, EdgeDataCenter(self.manager, 1, 1, 1, 1)))
        self._generate_devices(files.devices, device_count)
        for node in self.all_data_centers + self.edge_devices:
            if node.is_orchestrator:
                self.orchestrators.append(node)

    @property
    def all_data_centers(self) -> list[ComputingNode]:
        return self.cloud_nodes + self.edge_data_centers

    @property
    def all_nodes(self) -> list[ComputingNode]:
        return self.all_data_centers + self.routers + self.edge_devices

    def _create_datacenter(self, spec: DatacenterSpec, node: ComputingNode) -> ComputingNode:
        node.mips_per_core = spec.mips.sample()
        node.cores = int(spec.cores.sample_int())
        node.total_mips = node.mips_per_core * node.cores
        node.available_ram = float(spec.ram.sample())
        node.available_storage = float(spec.storage.sample())
        node.free_cores = node.cores
        node.is_sensor = node.mips_per_core <= 0 or node.cores <= 0 or node.available_storage <= 0
        node.is_orchestrator = spec.orchestrator
        node.name = spec.name
        node.energy_model.idle_consumption = spec.idle_consumption.sample()
        node.energy_model.max_consumption = spec.max_consumption.sample()
        node.mobility_model = MobilityModel(self.manager, Location(spec.x.sample(), spec.y.sample()))
        return node

    def _generate_devices(self, specs: list[DeviceSpec], device_count: int) -> None:
        for spec in specs:
            for _ in range(int(spec.percentage) * device_count // 100):
                self.edge_devices.append(self._create_device(spec))
        # Integer truncation can leave the last devices missing; PureEdgeSim
        # tops the count up with instances of the last device type.
        for _ in range(device_count - len(self.edge_devices)):
            self.edge_devices.append(self._create_device(specs[-1]))

    def _create_device(self, spec: DeviceSpec) -> ComputingNode:
        node = EdgeDevice(self.manager, 1, 1, 1, 1)
        node.mips_per_core = spec.mips.sample()
        node.cores = int(spec.cores.sample_int())
        node.total_mips = node.mips_per_core * node.cores
        node.available_ram = float(spec.ram.sample())
        node.available_storage = float(spec.storage.sample())
        node.free_cores = node.cores
        node.is_sensor = node.mips_per_core <= 0 or node.cores <= 0 or node.available_storage <= 0
        node.is_orchestrator = spec.orchestrator
        node.generates_tasks = spec.generates_tasks
        node.name = f"{spec.connectivity} device {node.id}"
        node.mobility_model = self._create_mobility_model(spec, node)
        node.mobility_model.speed = float(spec.speed.sample())
        node.mobility_model.min_pause_duration = spec.min_pause_duration.sample()
        node.mobility_model.max_pause_duration = spec.max_pause_duration.sample()
        node.mobility_model.min_mobility_duration = spec.min_mobility_duration.sample()
        node.mobility_model.max_mobility_duration = spec.max_mobility_duration.sample()
        node.mobility_model.set_parameters(spec.mobility_options)
        node.mobility_model.is_mobile = spec.mobile
        energy = node.energy_model
        energy.idle_consumption = spec.idle_consumption.sample()
        energy.max_consumption = spec.max_consumption.sample()
        energy.battery_powered = spec.battery
        energy.battery_capacity = spec.battery_capacity.sample()
        energy.initial_battery_level = spec.initial_battery_level.sample()
        if spec.battery:
            energy.cpu_energy_consumption = energy.battery_capacity * (1 - energy.initial_battery_level / 100)
        energy.set_connectivity_type(spec.connectivity, self.parameters)
        return node

    def _create_mobility_model(self, spec: DeviceSpec, node: ComputingNode) -> MobilityModel:
        position = Location(self._clamp_x(spec), self._clamp_y(spec))
        if spec.mobility_model:
            model = MobilityModelFactory.create(spec.mobility_model, self.manager, position)
        else:
            model = self.manager.default_mobility_model(self.manager, position)
        if isinstance(model, ReferencePointGroupMobilityModel):
            model.random = node.random
        return model

    def _clamp_x(self, spec: DeviceSpec) -> float:
        value = spec.x.sample() if spec.x is not None else self.random.random() * self.parameters.simulation_map_width
        return min(max(value, 0.0), self.parameters.simulation_map_width)

    def _clamp_y(self, spec: DeviceSpec) -> float:
        value = spec.y.sample() if spec.y is not None else self.random.random() * self.parameters.simulation_map_length
        return min(max(value, 0.0), self.parameters.simulation_map_length)


class DefaultTopologyCreator:
    """WAN router, MAN ring between edge data centers, access links and device links."""

    def __init__(self, manager, generator: ComputingNodesGenerator, files: ScenarioFiles) -> None:
        self.manager = manager
        self.generator = generator
        self.files = files
        self.parameters = manager.parameters
        self.graph = manager.network.graph

    def create(self) -> None:
        cloud = self.generator.cloud_nodes
        edge = self.generator.edge_data_centers
        router = None
        if self.parameters.one_shared_wan_network and cloud and edge:
            router = Router(self.manager)
            router.name = "WAN router"
            self.generator.routers.append(router)
            for node in edge:
                self._wan(node, router)
                self._wan(router, node)
            self._wan(router, cloud[0])
            self._wan(cloud[0], router)
        else:
            for node in edge:
                for cloud_node in cloud:
                    self._wan(node, cloud_node)
                    self._wan(cloud_node, node)
        for origin, destination in self.files.man_links:
            pair = self._by_name(edge, origin, destination)
            if pair:
                first, second = pair
                self._man(first, second)
                self._man(second, first)
        if cloud and not self.parameters.one_shared_wan_network:
            for node in cloud:
                self.graph.add_node(node)
        for node in self.generator.edge_devices:
            self.graph.add_node(node)
            self._connect_device(node)

    def _connect_device(self, node: ComputingNode) -> None:
        closest, distance = None, self.parameters.edge_data_centers_range
        for candidate in self.generator.edge_data_centers:
            gap = node.distance_to(candidate)
            if gap <= distance:
                closest, distance = candidate, gap
        bandwidth, delay, up_energy, down_energy = self._access_parameters(node)
        node.up_link = self._link(node, closest, bandwidth, delay, up_energy, LinkType.LAN) if closest else None
        node.down_link = self._link(closest, node, bandwidth, delay, down_energy, LinkType.LAN) if closest else None
        node.serving_edge_data_center = closest
        router = self.generator.routers[0] if self.generator.routers else \
            (self.generator.cloud_nodes[0] if self.generator.cloud_nodes else None)
        if router is not None:
            node.wan_up_link = self._link(node, router, self.parameters.wan_bandwidth, self.parameters.wan_delay,
                                          self.parameters.wan_energy_per_bit, LinkType.WAN)
            node.wan_down_link = self._link(router, node, self.parameters.wan_bandwidth, self.parameters.wan_delay,
                                           self.parameters.wan_energy_per_bit, LinkType.WAN)
            if router.type == NodeType.CLOUD:
                self.graph.add_node(router)

    def _access_parameters(self, node: ComputingNode) -> tuple[float, float, float, float]:
        parameters = self.parameters
        connectivity = node.energy_model.connectivity
        if connectivity == "cellular":
            return (parameters.cellular_bandwidth, parameters.cellular_delay,
                    parameters.cellular_device_transmission_energy, parameters.cellular_base_station_downlink_energy)
        if connectivity == "ethernet":
            return (parameters.ethernet_bandwidth, parameters.ethernet_delay, parameters.ethernet_energy_per_bit,
                    parameters.ethernet_energy_per_bit)
        return (parameters.wifi_bandwidth, parameters.wifi_delay, parameters.wifi_device_transmission_energy,
                parameters.wifi_access_point_reception_energy)

    def _link(self, source: ComputingNode, destination: ComputingNode, bandwidth: float, delay: float,
              energy: float, link_type: LinkType) -> NetworkLink:
        technology = LinkTechnology.ETHERNET
        if link_type == LinkType.LAN and destination.type == NodeType.EDGE_DEVICE:
            technology = LinkTechnology(destination.energy_model.connectivity)
        elif link_type == LinkType.LAN and source.type == NodeType.EDGE_DEVICE:
            technology = LinkTechnology(source.energy_model.connectivity)
        return self.graph.connect(source, destination, bandwidth, delay, energy, link_type, technology)

    def _wan(self, source: ComputingNode, destination: ComputingNode) -> None:
        self._link(source, destination, self.parameters.wan_bandwidth, self.parameters.wan_delay,
                   self.parameters.wan_energy_per_bit, LinkType.WAN)

    def _man(self, source: ComputingNode, destination: ComputingNode) -> None:
        self._link(source, destination, self.parameters.man_bandwidth, self.parameters.man_delay,
                   self.parameters.man_energy_per_bit, LinkType.MAN)

    @staticmethod
    def _by_name(nodes: list[ComputingNode], origin: str, destination: str):
        first = next((node for node in nodes if node.name == origin), None)
        second = next((node for node in nodes if node.name == destination), None)
        return (first, second) if first and second else None

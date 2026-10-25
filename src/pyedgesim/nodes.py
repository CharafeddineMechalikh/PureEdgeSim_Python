"""Computing nodes, their resources, energy model and execution queue."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .engine import Event, SimEntity
from .mobility import Location
from .randomness import Randomness

BITS_PER_MB = 8_000_000.0


class NodeType(Enum):
    CLOUD = "CLOUD"
    EDGE_DATACENTER = "EDGE_DATACENTER"
    EDGE_DEVICE = "EDGE_DEVICE"
    ROUTER = "ROUTER"


class NodeStatus(Enum):
    ALIVE = 0
    DEAD = 1


class EventType(Enum):
    """The tags PureEdgeSim passes as integers, named for readability."""

    PRINT_LOG = 1
    SHOW_PROGRESS = 2
    EXECUTE_TASK = 3
    TRANSFER_RESULTS_TO_ORCH = 4
    RESULT_RETURN_FINISHED = 5
    SEND_TO_ORCH = 6
    UPDATE_REAL_TIME_CHARTS = 7
    SEND_TASK_FROM_ORCH_TO_DESTINATION = 8
    NEXT_BATCH = 9
    SEND_REQUEST_FROM_DEVICE_TO_ORCH = 10
    SEND_REQUEST_FROM_ORCH_TO_DESTINATION = 11
    SEND_RESULTS_FROM_DESTINATION_TO_ORCH = 12
    SEND_RESULTS_FROM_ORCH_TO_DEVICE = 13
    TRANSFER_FINISHED = 14
    UPDATE_STATUS = 15
    EXECUTION_FINISHED = 16
    UPDATE_NETWORK = 17
    DOWNLOAD_CONTAINER = 18


TRANSMISSION = 0
RECEPTION = 1


@dataclass
class EnergyModelComputingNode:
    """Linear power model: idle draw per update tick plus a lump per executed task."""

    idle_consumption: float = 0.0
    max_consumption: float = 0.0
    battery_powered: bool = False
    battery_capacity: float = 0.0
    initial_battery_level: float = 100.0
    cpu_energy_consumption: float = 0.0
    network_energy_consumption: float = 0.0
    transmission_energy_per_bit: float = 0.0
    reception_energy_per_bit: float = 0.0
    connectivity: str = "wifi"

    def set_connectivity_type(self, connectivity: str, parameters) -> None:
        self.connectivity = connectivity
        if connectivity == "cellular":
            self.transmission_energy_per_bit = parameters.cellular_device_transmission_energy
            self.reception_energy_per_bit = parameters.cellular_device_reception_energy
        elif connectivity == "wifi":
            self.transmission_energy_per_bit = parameters.wifi_device_transmission_energy
            self.reception_energy_per_bit = parameters.wifi_device_reception_energy
        else:
            self.transmission_energy_per_bit = parameters.ethernet_energy_per_bit / 2
            self.reception_energy_per_bit = parameters.ethernet_energy_per_bit / 2

    def update_wireless_energy_consumption(self, size_in_bits: float, flag: int) -> None:
        # The rate charged for RECEPTION is the one named transmission in the
        # original framework, and the other way round; kept identical on purpose.
        if flag == RECEPTION:
            self.network_energy_consumption += size_in_bits * self.transmission_energy_per_bit
        else:
            self.network_energy_consumption += size_in_bits * self.reception_energy_per_bit

    def add_static_energy(self, seconds: float) -> None:
        self.cpu_energy_consumption += self.idle_consumption / 3600 * seconds

    def add_dynamic_energy(self, task_length: float, total_mips: float) -> None:
        if total_mips > 0:
            self.cpu_energy_consumption += (self.max_consumption - self.idle_consumption) / 3600 \
                * task_length / total_mips

    def get_total_energy_consumption(self) -> float:
        return self.cpu_energy_consumption + self.network_energy_consumption


class ComputingNode(SimEntity):
    NULL: "ComputingNode"

    def __init__(self, manager, mips_per_core: float, cores: int, storage: float, ram: float,
                 node_type: NodeType = NodeType.CLOUD) -> None:
        self.manager = manager
        self.engine = manager.engine
        super().__init__(manager.engine)
        self.id = manager.next_node_id()
        self.name = f"node {self.id}"
        self.type = node_type
        self.mips_per_core = float(mips_per_core)
        self.cores = int(cores)
        self.total_mips = self.mips_per_core * self.cores
        self.available_storage = float(storage)
        self.available_ram = float(ram)
        self.free_cores = self.cores
        self.status = NodeStatus.ALIVE
        self.energy_model = EnergyModelComputingNode()
        self.mobility_model: Location | None = None
        self.is_sensor = mips_per_core <= 0 or cores <= 0 or storage <= 0
        self.is_peripheral = False
        self.is_orchestrator = False
        self.generates_tasks = False
        self.application_placed = False
        self.application_placement_location = None
        self.assigned_tasks = 0
        self.executing_tasks: list = []
        self.task_queue: list = []
        self.total_executed_instructions = 0.0
        self.installed_containers: set = set()
        self.serving_edge_data_center = None
        self.death_time = -1.0
        self.random = Randomness.get_random()

    def set_mobility_model(self, model) -> "ComputingNode":
        self.mobility_model = model
        return self

    def is_alive(self) -> bool:
        return self.status == NodeStatus.ALIVE

    def is_dead(self) -> bool:
        return self.status == NodeStatus.DEAD

    def is_battery_powered(self) -> bool:
        return self.energy_model.battery_powered

    def get_current_location(self) -> Location:
        return self.mobility_model.current_location if self.mobility_model else Location()

    def distance_to(self, other: "ComputingNode") -> float:
        if self.mobility_model is None or other is None or other.mobility_model is None:
            return 0.0
        return self.mobility_model.distance_to(other)

    def get_container_mb(self, task) -> float:
        return task.container_size / BITS_PER_MB

    def is_ram_available(self, task) -> bool:
        return self.available_ram >= self.get_container_mb(task)

    def is_storage_available(self, task) -> bool:
        return self.available_storage >= self.get_container_mb(task)

    def has_enough_resources(self, task) -> bool:
        return self.is_ram_available(task) and self.is_storage_available(task)

    def is_battery_empty(self) -> bool:
        return self.is_battery_powered() and self.get_remaining_battery() <= 0

    def get_remaining_battery(self) -> float:
        return max(0.0, self.energy_model.battery_capacity - self.energy_model.get_total_energy_consumption())

    def get_remaining_battery_percentage(self) -> float:
        if self.energy_model.battery_capacity <= 0:
            return 0.0
        return 100 * self.get_remaining_battery() / self.energy_model.battery_capacity

    def get_cpu_usage_average(self) -> float:
        clock = self.engine.clock
        if self.total_mips <= 0 or clock <= 0:
            return 0.0
        return min(100.0, self.total_executed_instructions / (self.total_mips * clock) * 100)

    def get_cpu_usage_current(self) -> float:
        if self.total_mips <= 0:
            return 0.0
        return min(100.0, sum(task.length for task in self.executing_tasks) / self.total_mips * 100)

    def submit_task(self, task) -> None:
        task.arrival_time = self.engine.clock
        self.available_storage -= self.get_container_mb(task)
        if self.free_cores >= 1 and self.is_ram_available(task):
            self.start_execution(task)
        else:
            self.task_queue.append(task)

    def start_execution(self, task) -> None:
        self.free_cores -= 1
        self.available_ram -= self.get_container_mb(task)
        task.execution_start_time = self.engine.clock
        self.executing_tasks.append(task)
        self.energy_model.add_dynamic_energy(task.length, self.total_mips)
        task.execution_duration = task.length / self.mips_per_core
        self.schedule(self, task.execution_duration, EventType.EXECUTION_FINISHED, task)

    def execution_finished(self, task) -> None:
        self.free_cores += 1
        self.available_ram += self.get_container_mb(task)
        self.available_storage += self.get_container_mb(task)
        self.executing_tasks.remove(task)
        task.execution_finish_time = self.engine.clock
        self.total_executed_instructions += task.length
        self.manager.on_task_execution_finished(task, self)
        if self.task_queue and self.free_cores >= 1 and self.is_ram_available(self.task_queue[0]):
            self.start_execution(self.task_queue.pop(0))

    def update_status(self) -> None:
        # A dead node stops consuming and dies exactly once, so its death time is
        # the one recorded when the battery first went empty.
        if self.is_dead():
            return
        interval = self.manager.parameters.update_interval
        self.energy_model.add_static_energy(interval)
        if self.mobility_model is not None:
            self.mobility_model.update_location(self.engine.clock)
            self.manager.connect_with(self, self.mobility_model.get_closest_edge_data_center())
        if self.is_battery_empty():
            self.status = NodeStatus.DEAD
            self.death_time = self.engine.clock

    def process_event(self, event: Event) -> None:
        if event.tag == EventType.UPDATE_STATUS:
            self.update_status()
            self.schedule(self, self.manager.parameters.update_interval, EventType.UPDATE_STATUS)
        elif event.tag == EventType.EXECUTION_FINISHED:
            self.execution_finished(event.data)


class EdgeDevice(ComputingNode):
    def __init__(self, manager, mips_per_core, cores, storage, ram) -> None:
        super().__init__(manager, mips_per_core, cores, storage, ram, NodeType.EDGE_DEVICE)


class EdgeDataCenter(ComputingNode):
    def __init__(self, manager, mips_per_core, cores, storage, ram) -> None:
        super().__init__(manager, mips_per_core, cores, storage, ram, NodeType.EDGE_DATACENTER)
        self.is_peripheral = True


class CloudDataCenter(ComputingNode):
    def __init__(self, manager, mips_per_core, cores, storage, ram) -> None:
        super().__init__(manager, mips_per_core, cores, storage, ram, NodeType.CLOUD)


class Router(ComputingNode):
    def __init__(self, manager) -> None:
        super().__init__(manager, 0, 0, 0, 0, NodeType.ROUTER)
        self.is_sensor = True


def _build_null_node() -> ComputingNode:
    node = ComputingNode.__new__(ComputingNode)
    node.id = -1
    node.name = "NULL"
    node.type = NodeType.CLOUD
    node.manager = None
    node.engine = None
    node.mobility_model = None
    node.status = NodeStatus.DEAD
    node.is_sensor = True
    node.is_peripheral = False
    node.energy_model = EnergyModelComputingNode()
    return node


ComputingNode.NULL = _build_null_node()

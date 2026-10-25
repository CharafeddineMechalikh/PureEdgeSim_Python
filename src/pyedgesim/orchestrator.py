"""Offloading decisions, the counterpart of the taskorchestrator package."""
from __future__ import annotations

from .nodes import ComputingNode, NodeType

LAYERS = {
    "CLOUD_ONLY": (NodeType.CLOUD,),
    "EDGE_ONLY": (NodeType.EDGE_DATACENTER,),
    "MIST_ONLY": (NodeType.EDGE_DEVICE,),
    "MIST_AND_CLOUD": (NodeType.EDGE_DEVICE, NodeType.CLOUD),
    "EDGE_AND_CLOUD": (NodeType.EDGE_DATACENTER, NodeType.CLOUD),
    "MIST_AND_EDGE": (NodeType.EDGE_DEVICE, NodeType.EDGE_DATACENTER),
    "ALL": (NodeType.EDGE_DEVICE, NodeType.EDGE_DATACENTER, NodeType.CLOUD),
}
WEIGHTS = {NodeType.CLOUD: 1.8, NodeType.EDGE_DATACENTER: 1.2, NodeType.EDGE_DEVICE: 1.3}


class Orchestrator:
    def __init__(self, manager) -> None:
        self.manager = manager
        self.architecture_layers: tuple[NodeType, ...] = ()
        self.candidates: list[ComputingNode] = []
        self.history: dict[int, int] = {}

    def initialize(self, architecture: str) -> None:
        self.architecture_layers = LAYERS.get(architecture, ())
        nodes = self.manager.computing_nodes
        self.candidates = [node for node in nodes
                           if node.type in self.architecture_layers and not node.is_sensor]
        # PureEdgeSim counts the tasks each algorithm placed, independently of the
        # "assigned tasks" counter the nodes carry.
        self.history = {index: 0 for index in range(len(self.candidates))}

    def orchestrate(self, task, application_id: int = 0) -> ComputingNode | None:
        index = self.find_computing_node([task], self.manager.scenario.orchestration_algorithm, application_id)
        if index < 0:
            return None
        destination = self.candidates[index]
        task.destination = destination
        task.source_device.application_placement_location = destination
        task.source_device.application_placed = True
        return destination

    def find_computing_node(self, tasks, algorithm: str, application_id: int) -> int:
        eligible = [(index, node) for index, node in enumerate(self.candidates)
                    if self.offloading_is_possible(node, tasks[0])]
        if not eligible:
            return -1
        if algorithm == "ROUND_ROBIN":
            index = min(eligible, key=lambda pair: self.history[pair[0]])[0]
        else:
            index = self.trade_off(eligible, tasks[0])
        if index >= 0:
            self.history[index] += 1
        return index

    def trade_off(self, eligible, task) -> int:
        """The lowest score wins; on a tie the first candidate in list order is kept."""
        selected, best = -1, None
        for index, node in eligible:
            score = self.score(node, task, self.history[index])
            if best is None or best > score:
                best, selected = score, index
        return selected

    @staticmethod
    def score(node: ComputingNode, task, assigned: int = 0) -> float:
        weight = WEIGHTS.get(node.type, 1.2)
        return (assigned + 1) * weight * task.length / node.mips_per_core

    def offloading_is_possible(self, node: ComputingNode, task) -> bool:
        device = task.source_device
        orchestrator = task.get_orchestrator()
        if node.type == NodeType.CLOUD:
            return NodeType.CLOUD in self.architecture_layers
        if node.type == NodeType.EDGE_DATACENTER:
            if NodeType.EDGE_DATACENTER not in self.architecture_layers:
                return False
            return node in (device.serving_edge_data_center, orchestrator.serving_edge_data_center)
        if node.type == NodeType.EDGE_DEVICE:
            if (NodeType.EDGE_DEVICE not in self.architecture_layers or node.is_sensor
                    or not node.is_alive()):
                return False
            range_ = self.manager.parameters.edge_devices_range
            return (device.distance_to(node) <= range_
                    or (self.manager.parameters.enable_orchestrators and orchestrator.distance_to(node) <= range_))
        return False

    def results_returned(self, task) -> None:
        pass


class DefaultOrchestrator(Orchestrator):
    pass

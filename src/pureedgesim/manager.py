"""Simulation manager, event flow and metrics aggregation."""
from __future__ import annotations

from .engine import Engine, Event, SimEntity
from .config import ScenarioFiles
from .mobility import DefaultMobilityModel
from .network import DefaultNetworkModel, LinkTechnology, LinkType
from .nodes import ComputingNode, EventType, NodeStatus, NodeType
from .orchestrator import DefaultOrchestrator
from .parameters import SimulationParameters
from .randomness import Randomness
from .tasks import DefaultTaskGenerator, Task, TaskStatus
from .topology import ComputingNodesGenerator, DefaultTopologyCreator


class Scenario:
    def __init__(self, architecture: str, algorithm: str, devices_count: int) -> None:
        self.orchestration_architecture = architecture
        self.orchestration_algorithm = algorithm
        self.devices_count = devices_count

    def __repr__(self) -> str:
        return f"{self.orchestration_architecture}/{self.orchestration_algorithm}/{self.devices_count}"


class SimulationManager(SimEntity):
    """The hub: it owns the models, drives the task lifecycle and counts the results."""

    def __init__(self, engine: Engine, parameters: SimulationParameters, files: ScenarioFiles,
                 scenario: Scenario, custom_mobility_model=None, custom_orchestrator=None,
                 custom_network_model=None, custom_nodes_generator=None, custom_topology_creator=None,
                 custom_task_generator=None, custom_computing_node=None) -> None:
        super().__init__(engine)
        self.engine = engine
        self.parameters = parameters
        self.files = files
        self.scenario = scenario
        self.random = Randomness.get_random()
        self.default_mobility_model = custom_mobility_model or DefaultMobilityModel
        self.custom_orchestrator = custom_orchestrator
        self.custom_network_model = custom_network_model or DefaultNetworkModel
        self.custom_nodes_generator = custom_nodes_generator or ComputingNodesGenerator
        self.custom_topology_creator = custom_topology_creator or DefaultTopologyCreator
        self.custom_task_generator = custom_task_generator or DefaultTaskGenerator
        # The class every created node is built from, the counterpart of
        # setCustomComputingNode; None keeps the built-in classes.
        self.custom_computing_node = custom_computing_node
        self.node_id_counter = 0
        self.network: DefaultNetworkModel | None = None
        self.nodes_generator: ComputingNodesGenerator | None = None
        self.orchestrator = None
        self.tasks: list[Task] = []
        self.finished_tasks: set[int] = set()
        self.requests: dict[int, _RequestRecord] = {}
        self.metrics = _Metrics()
        self.registry: ComputingNode = ComputingNode.NULL
        self.applications = files.applications
        self.edge_only_list: list[ComputingNode] = []
        self.edge_devices: list[ComputingNode] = []
        self.computing_nodes: list[ComputingNode] = []
        self.device_to_device_links: dict[tuple[int, int], object] = {}

    def next_node_id(self) -> int:
        self.node_id_counter += 1
        return self.node_id_counter

    def start_simulation(self) -> None:
        self.network = self.custom_network_model(self)
        self.nodes_generator = self.custom_nodes_generator(self)
        self.nodes_generator.generate(self.files, self.scenario.devices_count)
        self.custom_topology_creator(self, self.nodes_generator, self.files).create()
        self.computing_nodes = self.nodes_generator.all_nodes
        self.edge_only_list = [node for node in self.nodes_generator.edge_data_centers if node.is_peripheral]
        self.edge_devices = self.nodes_generator.edge_devices
        self.registry = self.nodes_generator.cloud_nodes[0] if self.nodes_generator.cloud_nodes else ComputingNode.NULL
        self.orchestrator = (self.custom_orchestrator or DefaultOrchestrator)(self)
        self.orchestrator.initialize(self.scenario.orchestration_architecture)
        self.tasks = self.custom_task_generator(self).generate()
        # The tasks that enter the simulation immediately: a graph submits its roots,
        # the other subtasks wait until their dependencies return their results.
        self.root_tasks = [task for task in self.tasks if not task.dependencies]
        self.metrics.generated_tasks = len(self.tasks)
        for node in self.computing_nodes:
            if node.mobility_model is not None:
                node.mobility_model.generate_path()
            node.schedule(node, self.parameters.update_interval, EventType.UPDATE_STATUS)
        self._schedule_batch(0)
        self.schedule(self, self.parameters.simulation_duration, EventType.PRINT_LOG)

    def _d2d_parameters(self) -> tuple[float, float]:
        connectivity = self.edge_devices[0].energy_model.connectivity
        if connectivity == "cellular":
            return self.parameters.cellular_bandwidth, self.parameters.cellular_delay
        if connectivity == "ethernet":
            return self.parameters.ethernet_bandwidth, self.parameters.ethernet_delay
        return self.parameters.wifi_bandwidth, self.parameters.wifi_delay

    def _schedule_batch(self, start: int) -> None:
        end = min(start + self.parameters.batch_size, len(self.root_tasks))
        for index in range(start, end):
            task = self.root_tasks[index]
            delay = max(0.0, task.time - self.engine.clock)
            self.schedule(self, delay, EventType.SEND_TO_ORCH, task)
        if end < len(self.root_tasks):
            self.schedule(self, 0.0, EventType.NEXT_BATCH, end)

    def process_event(self, event: Event) -> None:
        if event.tag == EventType.SEND_TO_ORCH:
            self._send_to_orchestrator(event.data)
        elif event.tag == EventType.NEXT_BATCH:
            self._schedule_batch(event.data)
        elif event.tag == EventType.SEND_TASK_FROM_ORCH_TO_DESTINATION:
            self._send_from_orchestrator_to_destination(event.data)
        elif event.tag == EventType.RESULT_RETURN_FINISHED:
            self._results_returned(event.data)
        elif event.tag == EventType.PRINT_LOG:
            self._check_termination()

    def _send_to_orchestrator(self, task: Task) -> None:
        self._register_request(task)
        if self.task_failed(task, 0):
            return
        orchestrator = self._select_orchestrator(task)
        task.orchestrator = orchestrator
        if orchestrator is task.source_device:
            self.schedule(self, 0.0, EventType.SEND_TASK_FROM_ORCH_TO_DESTINATION, task)
            return
        self.network.send(task, task.request_size, self.network.route_for(task.source_device, orchestrator),
                          lambda finished, _progress: self.schedule(
                              self, 0.0, EventType.SEND_TASK_FROM_ORCH_TO_DESTINATION, finished),
                          "request to orchestrator")

    def _select_orchestrator(self, task: Task) -> ComputingNode:
        if not self.parameters.enable_orchestrators:
            return task.get_orchestrator()
        mode = self.parameters.deploy_orchestrator
        if mode == "MIST":
            return task.source_device
        if mode == "CLOUD":
            return self.registry
        if mode == "EDGE":
            return task.source_device.serving_edge_data_center or self.registry
        candidates = self.nodes_generator.orchestrators
        if not candidates:
            return self.registry
        return min(candidates, key=lambda node: self.network.graph.path_delay(task.source_device, node))

    def _send_from_orchestrator_to_destination(self, task: Task) -> None:
        if self.task_failed(task, 1):
            return
        device = task.source_device
        if device.application_placed and device.application_placement_location is not None:
            destination = device.application_placement_location
            task.destination = destination
            destination.assigned_tasks += 1
        else:
            destination = self.orchestrator.orchestrate(task, task.application_id)
        if destination is None:
            self._fail(task, TaskStatus.NO_OFFLOADING_DESTINATIONS, "no destination")
            return
        self.metrics.network_requests += 1
        self._count_level(task)

        def submit(_task, _progress):
            if self.task_failed(task, 2):
                return
            destination.submit_task(task)

        if self._needs_container(task, destination):
            self.network.graph.add_node(destination)
            route = self.network.route_for(self.registry, destination)

            def after_download(_task, _progress):
                destination.installed_containers.add(task.application_id)
                self._send_request_to_destination(task, destination, submit)

            self.network.send(task, task.container_size, route, after_download, "container download")
        else:
            self._send_request_to_destination(task, destination, submit)

    def _needs_container(self, task: Task, destination: ComputingNode) -> bool:
        return (self.parameters.enable_registry and self.parameters.registry_mode == "CLOUD"
                and destination.type != NodeType.CLOUD and task.application_id not in destination.installed_containers)

    def _send_request_to_destination(self, task: Task, destination: ComputingNode, callback) -> None:
        route = self.network.route_for(task.get_orchestrator(), destination)
        self.network.send(task, task.request_size, route, callback, "task to destination")

    def on_task_execution_finished(self, task: Task, node: ComputingNode) -> None:
        self.metrics.executed_tasks += 1
        self.metrics.total_execution_time += task.actual_cpu_time
        self.metrics.total_waiting_time += task.waiting_time
        orchestrator = task.get_orchestrator()

        def at_orchestrator(_task, _progress):
            if orchestrator is task.source_device:
                self._results_returned(task)
                return
            self.network.send(task, task.result_size, self.network.route_for(orchestrator, task.source_device),
                              lambda _t, _p: self._results_returned(task), "results to device")

        self.network.send(task, task.result_size, self.network.route_for(node, orchestrator), at_orchestrator,
                          "results to orchestrator")

    def _results_returned(self, task: Task) -> None:
        if task.id in self.finished_tasks:
            return
        self.finished_tasks.add(task.id)
        self.task_failed(task, 3)
        if task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.SUCCESS
            self.metrics.succeeded_tasks += 1
            self._count_success(task)
            self._release_dependents(task)
            self._request_task_finished(task, False)
        self.orchestrator.results_returned(task)

    def _release_dependents(self, task: Task, with_results: bool = True) -> None:
        """Submits the subtasks whose last dependency has just returned its results.

        The output of the parent is added to the request size of the child, so the
        payload of a dependency travels over the network.
        """
        for dependent in task.dependents:
            if self._is_terminal(dependent):
                continue
            if with_results:
                dependent.request_size += task.result_size
            if dependent.dependency_finished():
                dependent.time = self.engine.clock
                self.schedule(self, 0.0, EventType.SEND_TO_ORCH, dependent)

    def _fail_dependents(self, task: Task) -> None:
        """Fails the subtasks that will never receive their input.

        An optional subtask is skipped instead of failing the request, and the
        request continues without its results.
        """
        for dependent in task.dependents:
            if self._is_terminal(dependent):
                continue
            if dependent.optional:
                self._skip_task(dependent)
                continue
            dependent.failed = True
            dependent.status = TaskStatus.FAILED_BECAUSE_DEPENDENCY_FAILED
            self.metrics.dependency_failures += 1
            self._request_task_finished(dependent, True)
            self._fail_dependents(dependent)

    def _is_terminal(self, task: Task) -> bool:
        return task.failed or task.status == TaskStatus.SKIPPED

    def _skip_task(self, task: Task) -> None:
        """Skips an optional subtask whose input can never be complete."""
        task.status = TaskStatus.SKIPPED
        self.metrics.tasks_skipped += 1
        self._request_task_finished(task, False)
        self._release_dependents(task, False)

    def _register_request(self, task: Task) -> None:
        if task.request_id < 0 or task.request_id in self.requests:
            return
        self.requests[task.request_id] = _RequestRecord(task.request_start_time, task.request_task_count)
        self.metrics.generated_requests += 1

    def _request_task_finished(self, task: Task, failed: bool) -> None:
        """Records one terminal task of a request; completes the request on the last one."""
        if task.request_id < 0:
            return
        self._register_request(task)
        request = self.requests[task.request_id]
        if failed:
            request.failed = True
        request.remaining -= 1
        if request.remaining > 0:
            return
        if request.failed:
            self.metrics.failed_requests += 1
            return
        self.metrics.successful_requests += 1
        self.metrics.total_request_makespan += self.engine.clock - request.start_time

    def _count_level(self, task: Task) -> None:
        if task.level_counted or task.destination is None:
            return
        task.level_counted = True
        if task.destination.type == NodeType.CLOUD:
            self.metrics.cloud_tasks += 1
        elif task.destination.type == NodeType.EDGE_DATACENTER:
            self.metrics.edge_tasks += 1
        elif task.destination.type == NodeType.EDGE_DEVICE:
            self.metrics.mist_tasks += 1

    def _count_success(self, task: Task) -> None:
        if task.destination is None:
            return
        if task.destination.type == NodeType.CLOUD:
            self.metrics.cloud_successes += 1
        elif task.destination.type == NodeType.EDGE_DATACENTER:
            self.metrics.edge_successes += 1
        elif task.destination.type == NodeType.EDGE_DEVICE:
            self.metrics.mist_successes += 1

    def task_failed(self, task: Task, phase: int) -> bool:
        device, orchestrator, destination = task.source_device, task.get_orchestrator(), task.destination
        if phase == 0 and not device.is_alive():
            # Died before offloading, so the task is never sent: it counts as not
            # generated rather than failed.
            if not task.failed:
                task.failed = True
                task.status = TaskStatus.FAILED_DUE_TO_DEVICE_DEATH
                task.source_device.application_placed = False
                self.metrics.not_generated += 1
                self._request_task_finished(task, True)
                self._fail_dependents(task)
            return True
        if phase == 1:
            if not orchestrator.is_alive():
                return self._fail(task, TaskStatus.FAILED_DUE_TO_DEVICE_DEATH, "orchestrator dead")
            if (orchestrator is not device and orchestrator.type == NodeType.EDGE_DEVICE
                    and device.distance_to(orchestrator) > self.parameters.edge_devices_range):
                return self._fail(task, TaskStatus.FAILED_DUE_TO_DEVICE_MOBILITY, "orchestrator out of range")
        if phase == 2:
            if destination is None or not destination.is_alive():
                return self._fail(task, TaskStatus.FAILED_DUE_TO_DEVICE_DEATH, "destination dead")
            if not destination.has_enough_resources(task):
                return self._fail(task, TaskStatus.INSUFFICIENT_RESOURCES, "insufficient resources")
            if device.distance_to(destination) > self.parameters.edge_data_centers_range and \
                    destination.type == NodeType.EDGE_DEVICE:
                return self._fail(task, TaskStatus.FAILED_DUE_TO_DEVICE_MOBILITY, "destination out of range")
        if phase == 3:
            if destination is not None and destination.is_dead():
                return self._fail(task, TaskStatus.FAILED_DUE_TO_DEVICE_DEATH, "destination died")
            if task.total_delay >= task.max_latency:
                return self._fail(task, TaskStatus.FAILED_DUE_TO_DELAY, "latency exceeded")
            # The request missed its end-to-end deadline even if this subtask met
            # its own bound, measured from its release.
            if task.request_deadline > 0 and self.engine.clock >= task.request_deadline:
                return self._fail(task, TaskStatus.FAILED_DUE_TO_DELAY, "request deadline exceeded")
        return False

    def _fail(self, task: Task, status: TaskStatus, reason: str) -> bool:
        if task.failed:
            return True
        task.failed = True
        task.status = status
        task.source_device.application_placed = False
        if status == TaskStatus.FAILED_DUE_TO_DELAY:
            self.metrics.delay_failures += 1
        elif status == TaskStatus.FAILED_DUE_TO_DEVICE_DEATH:
            self.metrics.death_failures += 1
        elif status == TaskStatus.FAILED_DUE_TO_DEVICE_MOBILITY:
            self.metrics.mobility_failures += 1
        else:
            self.metrics.not_executed += 1
        self._fail_dependents(task)
        self._request_task_finished(task, True)
        return True

    def connect_with(self, device: ComputingNode, data_center) -> None:
        if data_center is None or data_center is ComputingNode.NULL or device.serving_edge_data_center is data_center:
            return
        bandwidth, delay, up_energy, down_energy = self._access_energy_for(device)
        device.up_link = self.network.graph.connect(device, data_center, bandwidth, delay, up_energy, LinkType.LAN,
                                                    LinkTechnology(device.energy_model.connectivity))
        device.down_link = self.network.graph.connect(data_center, device, bandwidth, delay, down_energy, LinkType.LAN,
                                                      LinkTechnology(device.energy_model.connectivity))
        device.serving_edge_data_center = data_center

    def _access_energy_for(self, device: ComputingNode) -> tuple[float, float, float, float]:
        parameters = self.parameters
        connectivity = device.energy_model.connectivity
        if connectivity == "cellular":
            return (parameters.cellular_bandwidth, parameters.cellular_delay,
                    parameters.cellular_device_transmission_energy, parameters.cellular_base_station_downlink_energy)
        if connectivity == "ethernet":
            return (parameters.ethernet_bandwidth, parameters.ethernet_delay, parameters.ethernet_energy_per_bit,
                    parameters.ethernet_energy_per_bit)
        return (parameters.wifi_bandwidth, parameters.wifi_delay, parameters.wifi_device_transmission_energy,
                parameters.wifi_access_point_reception_energy)

    def access_link(self, device: ComputingNode, other_end: ComputingNode):
        """The link the device uses to leave the mist layer for this destination."""
        if other_end is device.serving_edge_data_center:
            return device.up_link
        return device.wan_up_link

    def device_to_device_route(self, source: ComputingNode, destination: ComputingNode) -> list:
        if source.distance_to(destination) > self.parameters.edge_devices_range:
            return []
        link = self.device_to_device_links.get((source.id, destination.id))
        if link is None:
            bandwidth, delay = self._d2d_parameters()
            link = self.network.graph.connect(source, destination, bandwidth, delay, 0.0, LinkType.LAN,
                                              LinkTechnology(source.energy_model.connectivity))
            self.device_to_device_links[(source.id, destination.id)] = link
        return [link]

    def _check_termination(self) -> None:
        pending = self.metrics.generated_tasks - len(self.finished_tasks) - self._failed_without_execution()
        limit = self.parameters.simulation_duration + 3600
        if self.parameters.wait_for_all_tasks and pending > 0 and self.engine.clock < limit:
            self.schedule(self, 10.0, EventType.PRINT_LOG)
            return
        self.engine.terminate()

    def _failed_without_execution(self) -> int:
        return sum(1 for task in self.tasks if task.failed and task.id not in self.finished_tasks)

    def get_tasks_sent_number(self) -> int:
        return sum(1 for task in self.tasks if task.destination is not None)


class _Metrics:
    def __init__(self) -> None:
        self.generated_tasks = 0
        self.not_generated = 0
        self.succeeded_tasks = 0
        self.executed_tasks = 0
        self.network_requests = 0
        self.total_execution_time = 0.0
        self.total_waiting_time = 0.0
        self.delay_failures = 0
        self.death_failures = 0
        self.mobility_failures = 0
        self.not_executed = 0
        self.dependency_failures = 0
        self.dead_devices = 0
        self.cloud_tasks = 0
        self.edge_tasks = 0
        self.mist_tasks = 0
        self.cloud_successes = 0
        self.edge_successes = 0
        self.mist_successes = 0
        self.tasks_skipped = 0
        self.generated_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_request_makespan = 0.0


class _RequestRecord:
    """One request of a service graph, completed when all its subtasks are terminal."""

    def __init__(self, start_time: float, task_count: int) -> None:
        self.start_time = start_time
        self.remaining = task_count
        self.failed = False

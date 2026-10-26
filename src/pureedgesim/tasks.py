"""Tasks and workload generation, the counterpart of the taskgenerator package."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .nodes import ComputingNode


class TaskStatus(Enum):
    SUCCESS = 0
    RUNNING = 1
    FAILED_DUE_TO_DELAY = 2
    FAILED_DUE_TO_DEVICE_DEATH = 3
    FAILED_DUE_TO_DEVICE_MOBILITY = 4
    INSUFFICIENT_RESOURCES = 5
    NO_OFFLOADING_DESTINATIONS = 6
    NULL = 7
    FAILED_BECAUSE_DEPENDENCY_FAILED = 8


@dataclass
class Task:
    id: int
    type: str
    application_id: int
    length: float
    container_size: float
    request_size: float
    result_size: float
    max_latency: float
    time: float
    source_device: ComputingNode
    registry: ComputingNode
    orchestrator: ComputingNode = None
    destination: ComputingNode = None
    status: TaskStatus = TaskStatus.RUNNING
    arrival_time: float = 0.0
    execution_start_time: float = 0.0
    execution_finish_time: float = 0.0
    execution_duration: float = 0.0
    total_network_time: float = 0.0
    network_hops: list = field(default_factory=list)
    level_counted: bool = False
    failed: bool = False
    subtask_name: str | None = None
    dependencies: list = field(default_factory=list)
    dependents: list = field(default_factory=list)
    remaining_dependencies: int = 0

    def add_dependency(self, parent: "Task") -> None:
        """Registers a parent whose results must return before this task may run."""
        self.dependencies.append(parent)
        self.remaining_dependencies += 1

    def add_dependent(self, child: "Task") -> None:
        self.dependents.append(child)

    def dependency_finished(self) -> bool:
        """Records that one parent returned its results; true once the last one has."""
        if self.remaining_dependencies > 0:
            self.remaining_dependencies -= 1
        return self.remaining_dependencies == 0

    @property
    def waiting_time(self) -> float:
        return self.execution_start_time - self.arrival_time

    @property
    def actual_cpu_time(self) -> float:
        return self.execution_finish_time - self.execution_start_time

    @property
    def total_delay(self) -> float:
        return self.total_network_time + self.waiting_time + self.actual_cpu_time

    def is_served(self) -> bool:
        return self.destination is not None

    def get_orchestrator(self) -> ComputingNode:
        if self.orchestrator is None:
            self.orchestrator = self.source_device
            self.source_device.is_orchestrator = True
        return self.orchestrator


class DefaultTaskGenerator:
    """Pre-generates the whole workload, exactly like DefaultTaskGenerator in Java."""

    def __init__(self, manager) -> None:
        self.manager = manager
        self.parameters = manager.parameters
        self.random = manager.random

    def generate(self) -> list[Task]:
        applications = self.manager.applications
        devices = [node for node in self.manager.edge_devices if node.generates_tasks and node.is_alive()]
        if not devices or not applications:
            return []
        tasks: list[Task] = []
        pool = list(devices)
        identifier = 1
        for index, application in enumerate(applications):
            if index == len(applications) - 1:
                selected, pool = pool, []
            else:
                count = int(application.usage_percentage * len(devices) / 100)
                selected = [pool.pop(self.random.randrange(len(pool))) for _ in range(min(count, len(pool)))]
            for device in selected:
                identifier = self._generate_for_device(device, application, tasks, identifier)
        tasks.sort(key=lambda task: task.time)
        return tasks

    def _generate_for_device(self, device, application, tasks: list[Task], identifier: int) -> int:
        if application.arrival_distribution is not None:
            return self._generate_arriving(device, application, tasks, identifier)
        for minute in range(int(self.parameters.simulation_duration / 60)):
            # A burst of <rate> tasks is dropped inside each minute, evenly spaced.
            time = minute * 60 + self.random.randrange(15)
            rate = max(0, int(application.rate.sample_int()))
            if rate == 0:
                continue
            spacing = 60 // rate
            for _ in range(rate):
                time += spacing
                generated, identifier = self._create_tasks(device, application, time, identifier)
                tasks.extend(generated)
        return identifier

    def _generate_arriving(self, device, application, tasks: list[Task], identifier: int) -> int:
        arrival = application.arrival_distribution
        duration = self.parameters.simulation_duration
        # The device is not assumed to be busy at the very start of the simulation.
        time = self.random.random() * max(1.0, arrival.sample())
        time = max(1.0, float(int(time)))
        while time < duration:
            generated, identifier = self._create_tasks(device, application, int(time), identifier)
            tasks.extend(generated)
            # A gap of less than one second would keep the loop busy without moving.
            time += max(1.0, arrival.sample())
        return identifier

    def _create_tasks(self, device, application, time: float, identifier: int) -> tuple[list[Task], int]:
        """Every task of one request: a single task, or one task per subtask of a graph."""
        if not application.has_subtasks:
            return [self._create_task(device, application, time, identifier)], identifier + 1
        tasks: list[Task] = []
        by_name: dict[str, Task] = {}
        request_id = self.manager.applications.index(application)
        for subtask in application.subtasks:
            task = Task(
                id=identifier,
                type=application.type,
                application_id=request_id,
                length=subtask.task_length.sample(),
                container_size=subtask.container_size.sample(),
                request_size=subtask.request_size.sample(),
                result_size=subtask.results_size.sample(),
                max_latency=subtask.latency.sample(),
                time=time,
                source_device=device,
                registry=self.manager.registry,
                subtask_name=subtask.name,
            )
            identifier += 1
            by_name[subtask.name] = task
            tasks.append(task)
        for subtask in application.subtasks:
            child = by_name[subtask.name]
            for parent_name in subtask.dependencies:
                parent = by_name[parent_name]
                parent.add_dependent(child)
                child.add_dependency(parent)
        return tasks, identifier

    def _create_task(self, device, application, time: float, identifier: int) -> Task:
        return Task(
            id=identifier,
            type=application.type,
            application_id=self.manager.applications.index(application),
            length=application.task_length.sample(),
            container_size=application.container_size.sample(),
            request_size=application.request_size.sample(),
            result_size=application.results_size.sample(),
            max_latency=application.latency.sample(),
            time=time,
            source_device=device,
            registry=self.manager.registry,
        )

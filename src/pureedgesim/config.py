"""Parsers for applications.xml, cloud.xml, edge_datacenters.xml and edge_devices.xml."""
from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path

from .distribution import Distribution, ScaledDistribution, distribution_from_element

KILOBYTES_TO_BITS = 8000
BYTES_TO_BITS = 8


def _child(parent: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return parent.find(name)


def _distribution(parent: ElementTree.Element, name: str, path: Path, default: float | None = None,
                  scale: float | None = None) -> Distribution:
    element = _child(parent, name)
    if element is None:
        if default is None:
            raise ValueError(f"{path}: the <{name}> element is missing inside <{parent.tag}>")
        from .distribution import ConstantDistribution
        return ConstantDistribution(default)
    distribution = distribution_from_element(element)
    return distribution if scale is None else ScaledDistribution(distribution, scale)


def _text(parent: ElementTree.Element, name: str, default: str = "") -> str:
    element = _child(parent, name)
    if element is None or (element.text or "").strip() == "":
        return default
    return element.text.strip()


def _boolean(parent: ElementTree.Element, name: str, default: bool = False) -> bool:
    return _text(parent, name, str(default)).strip().lower() == "true"


@dataclass
class Subtask:
    """One node of a service graph: a task that waits for its dependencies."""
    name: str
    dependencies: tuple[str, ...]
    latency: Distribution
    container_size: Distribution
    request_size: Distribution
    results_size: Distribution
    task_length: Distribution

    @property
    def is_root(self) -> bool:
        return not self.dependencies


@dataclass
class Application:
    name: str
    type: str
    rate: Distribution
    usage_percentage: float
    latency: Distribution
    container_size: Distribution
    request_size: Distribution
    results_size: Distribution
    task_length: Distribution
    arrival_distribution: Distribution | None = None
    subtasks: tuple[Subtask, ...] = ()

    @property
    def has_subtasks(self) -> bool:
        return bool(self.subtasks)

    def get_rate(self) -> float:
        return self.rate.mean()

    def get_latency(self) -> float:
        return self.latency.mean()

    def get_container_size(self) -> float:
        return self.container_size.mean()

    def get_request_size(self) -> float:
        return self.request_size.mean()

    def get_results_size(self) -> float:
        return self.results_size.mean()

    def get_task_length(self) -> float:
        return self.task_length.mean()


@dataclass
class DatacenterSpec:
    name: str
    periphery: bool
    orchestrator: bool
    x: Distribution
    y: Distribution
    cores: Distribution
    mips: Distribution
    ram: Distribution
    storage: Distribution
    idle_consumption: Distribution
    max_consumption: Distribution


@dataclass
class DeviceSpec:
    connectivity: str
    mobile: bool
    mobility_model: str | None
    mobility_options: dict[str, str]
    speed: Distribution
    min_pause_duration: Distribution
    max_pause_duration: Distribution
    min_mobility_duration: Distribution
    max_mobility_duration: Distribution
    battery: bool
    percentage: float
    battery_capacity: Distribution
    initial_battery_level: Distribution
    idle_consumption: Distribution
    max_consumption: Distribution
    orchestrator: bool
    generates_tasks: bool
    cores: Distribution
    mips: Distribution
    ram: Distribution
    storage: Distribution
    x: Distribution | None = None
    y: Distribution | None = None


@dataclass
class ScenarioFiles:
    applications: list[Application] = field(default_factory=list)
    cloud: list[DatacenterSpec] = field(default_factory=list)
    edge_datacenters: list[DatacenterSpec] = field(default_factory=list)
    devices: list[DeviceSpec] = field(default_factory=list)
    man_links: list[tuple[str, str]] = field(default_factory=list)
    edge_device_count: int = 0

    def get_cloud_count(self) -> int:
        return sum(1 for spec in self.cloud if spec is not None)

    def get_edge_count(self) -> int:
        return len(self.edge_datacenters)


def _arrival(element: ElementTree.Element, rate: Distribution, path: Path) -> Distribution | None:
    """The optional <arrival> element: the gap between two tasks, in seconds."""
    arrival = _child(element, "arrival")
    if arrival is None:
        return None
    if "distribution" in arrival.attrib:
        distribution = distribution_from_element(arrival)
        return distribution if distribution.min >= 0 else distribution.bounded(0.0, float("inf"))
    mean_gap = 60 / max(1, rate.mean())
    value = (arrival.text or "").strip().lower()
    if value in ("", "constant", "even"):
        return None
    if value in ("poisson", "exponential"):
        from .distribution import ExponentialDistribution
        return ExponentialDistribution(mean_gap)
    if value in ("uniform", "random"):
        from .distribution import UniformDistribution
        return UniformDistribution(0, 2 * mean_gap)
    raise ValueError(f'{path}: unknown arrival pattern "{value}" in the '
                     f'"{element.attrib.get("name", "")}" application, expected "constant", "poisson", '
                     f'"uniform", or a distribution')


def _root(path: Path) -> ElementTree.Element:
    """Parses an XML file and names it in the error when the markup is invalid."""
    try:
        return ElementTree.parse(path).getroot()
    except ElementTree.ParseError as error:
        raise ValueError(f"{path}: {error}") from error


SUBTASK_ATTRIBUTES = {"name", "depends_on", "task_length", "request_size", "results_size", "container_size",
                      "latency"}


def _subtask_error(application: str, subtask: str, reason: str) -> str:
    return f'the "{subtask}" subtask of the "{application}" application {reason}'


def _subtask_dependencies(element: ElementTree.Element, name: str, application: str, path: Path) -> tuple[str, ...]:
    """The comma separated depends_on attribute, empty for a root subtask."""
    raw = (element.attrib.get("depends_on") or "").strip()
    if not raw:
        return ()
    dependencies: list[str] = []
    for part in raw.split(","):
        dependency = part.strip()
        if not dependency:
            raise ValueError(f'{path}: ' + _subtask_error(application, name,
                                                           'has an empty name in its "depends_on" attribute'))
        if dependency == name:
            raise ValueError(f"{path}: " + _subtask_error(application, name, "cannot depend on itself"))
        if dependency not in dependencies:
            dependencies.append(dependency)
    return tuple(dependencies)


def _subtask_distribution(element: ElementTree.Element, attribute: str, inherited: Distribution, scale: float,
                          application: str, name: str, path: Path) -> Distribution:
    """A subtask attribute overrides the application value; an empty one inherits it."""
    from .distribution import ConstantDistribution
    raw = (element.attrib.get(attribute) or "").strip()
    if not raw:
        return inherited
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f'{path}: ' + _subtask_error(application, name,
                                                      f'has a non-numeric "{attribute}" value "{raw}"')) from error
    if value <= 0 or value == float("inf"):
        raise ValueError(f"{path}: " + _subtask_error(application, name,
                                                      f'has an invalid "{attribute}" value "{raw}", expected a '
                                                      f"positive number"))
    return ConstantDistribution(value * scale)


def _subtasks(element: ElementTree.Element, application: "Application", path: Path) -> tuple[Subtask, ...]:
    """Reads the optional <subtask> elements of an application and validates the graph."""
    elements = element.findall("subtask")
    if not elements:
        return ()
    subtasks: list[Subtask] = []
    names: set[str] = set()
    for index, subtask in enumerate(elements):
        name = (subtask.attrib.get("name") or "").strip()
        display = name or f"subtask {index + 1}"
        for attribute in subtask.attrib:
            if attribute not in SUBTASK_ATTRIBUTES:
                raise ValueError(f"{path}: " + _subtask_error(application.name, display,
                                                              f'has an unknown attribute "{attribute}", expected '
                                                              + ", ".join(sorted(SUBTASK_ATTRIBUTES))))
        if not name:
            raise ValueError(f"{path}: " + _subtask_error(application.name, display,
                                                          'has no "name" attribute'))
        if name in names:
            raise ValueError(f"{path}: " + _subtask_error(application.name, name, "is declared more than once"))
        names.add(name)
        subtasks.append(Subtask(
            name=name,
            dependencies=_subtask_dependencies(subtask, name, application.name, path),
            latency=_subtask_distribution(subtask, "latency", application.latency, 1, application.name, name, path),
            container_size=_subtask_distribution(subtask, "container_size", application.container_size,
                                                 KILOBYTES_TO_BITS, application.name, name, path),
            request_size=_subtask_distribution(subtask, "request_size", application.request_size,
                                               KILOBYTES_TO_BITS, application.name, name, path),
            results_size=_subtask_distribution(subtask, "results_size", application.results_size,
                                               KILOBYTES_TO_BITS, application.name, name, path),
            task_length=_subtask_distribution(subtask, "task_length", application.task_length, 1, application.name,
                                              name, path),
        ))
    _check_graph(subtasks, application.name, path)
    return tuple(subtasks)


def _check_graph(subtasks: list[Subtask], application: str, path: Path) -> None:
    """Rejects unknown dependencies and cycles (a topological sort that never empties)."""
    by_name = {subtask.name: subtask for subtask in subtasks}
    for subtask in subtasks:
        for dependency in subtask.dependencies:
            if dependency not in by_name:
                raise ValueError(f"{path}: " + _subtask_error(application, subtask.name,
                                                              f'unknown dependency "{dependency}"'))
    remaining = {subtask.name: len(subtask.dependencies) for subtask in subtasks}
    ready = [subtask for subtask in subtasks if not subtask.dependencies]
    visited = 0
    while ready:
        current = ready.pop()
        visited += 1
        for subtask in subtasks:
            if current.name in subtask.dependencies:
                remaining[subtask.name] -= 1
                if remaining[subtask.name] == 0:
                    ready.append(subtask)
    if visited != len(subtasks):
        cyclic = ", ".join(name for name, count in remaining.items() if count > 0)
        raise ValueError(f"{path}: " + _subtask_error(application, cyclic,
                                                      "is part of a dependency cycle"))


def load_applications(path: Path) -> list[Application]:
    root = _root(path)
    applications: list[Application] = []
    for element in root.findall("application"):
        rate = _distribution(element, "rate", path)
        application = Application(
            name=element.attrib.get("name", element.attrib.get("id", f"application {len(applications)}")),
            type=_text(element, "type", "Unknown"),
            rate=rate,
            usage_percentage=float(_text(element, "usage_percentage", "0") or 0),
            latency=_distribution(element, "latency", path),
            container_size=_distribution(element, "container_size", path, scale=KILOBYTES_TO_BITS),
            request_size=_distribution(element, "request_size", path, scale=KILOBYTES_TO_BITS),
            results_size=_distribution(element, "results_size", path, scale=KILOBYTES_TO_BITS),
            task_length=_distribution(element, "task_length", path),
            arrival_distribution=_arrival(element, rate, path),
        )
        application.subtasks = _subtasks(element, application, path)
        applications.append(application)
    if not applications:
        raise ValueError(f"{path}: no <application> element found")
    for application in applications:
        if application.get_rate() <= 0:
            raise ValueError(f'{path}: application "{application.name}" must have rate > 0')
        if application.usage_percentage <= 0 and application is not applications[-1]:
            raise ValueError(f'{path}: application "{application.name}" must have usage_percentage > 0')
    return applications


def _datacenter_spec(element: ElementTree.Element, path: Path, name: str, location_required: bool) -> DatacenterSpec:
    location = _child(element, "location")
    if location is None:
        from .distribution import ConstantDistribution
        if location_required:
            raise ValueError(f"{path}: the data center <{name}> has no <location> element")
        location = element
    return DatacenterSpec(
        name=name,
        periphery=_boolean(element, "periphery", False),
        orchestrator=_boolean(element, "isOrchestrator", False),
        x=_distribution(location, "x_pos", path, 0),
        y=_distribution(location, "y_pos", path, 0),
        cores=_distribution(element, "cores", path, 1),
        mips=_distribution(element, "mips", path, 1000),
        ram=_distribution(element, "ram", path, 1000),
        storage=_distribution(element, "storage", path, 1000),
        idle_consumption=_distribution(element, "idleConsumption", path, 0),
        max_consumption=_distribution(element, "maxConsumption", path, 0),
    )


def load_cloud(path: Path) -> list[DatacenterSpec]:
    root = _root(path)
    return [_datacenter_spec(element, path, element.attrib.get("name", f"cloud {index}"), False)
            for index, element in enumerate(root.findall("datacenter"))]


def load_edge_datacenters(path: Path) -> tuple[list[DatacenterSpec], list[tuple[str, str]]]:
    root = _root(path)
    specs = [_datacenter_spec(element, path, element.attrib.get("name", f"dc{index + 1}"), True)
             for index, element in enumerate(root.findall("datacenter"))]
    links: list[tuple[str, str]] = []
    network_links = _child(root, "network_links")
    if network_links is not None:
        for link in network_links.findall("link"):
            links.append((_text(link, "from"), _text(link, "to")))
    positions = {(round(spec.x.mean(), 6), round(spec.y.mean(), 6)) for spec in specs}
    if len(positions) != len(specs):
        raise ValueError(f"{path}: two edge data centers share the same location")
    return specs, links


def load_devices(path: Path) -> list[DeviceSpec]:
    root = _root(path)
    specs: list[DeviceSpec] = []
    for element in root.findall("device"):
        mobility = _child(element, "mobility")
        mobile = (mobility is None) or _boolean(element, "mobility", False)
        if mobility is not None:
            mobile = (mobility.text or "").strip().lower() != "false"
        options = {key.lower(): value for key, value in (mobility.attrib if mobility is not None else {}).items()}
        model = options.pop("model", None)
        location = _child(element, "location")
        specs.append(DeviceSpec(
            connectivity=_text(element, "connectivity", "wifi").lower(),
            mobile=mobile,
            mobility_model=model,
            mobility_options=options,
            speed=_distribution(element, "speed", path, 0),
            min_pause_duration=_distribution(element, "minPauseDuration", path, 0),
            max_pause_duration=_distribution(element, "maxPauseDuration", path, 0),
            min_mobility_duration=_distribution(element, "minMobilityDuration", path, 0),
            max_mobility_duration=_distribution(element, "maxMobilityDuration", path, 0),
            battery=_boolean(element, "battery", False),
            percentage=float(_text(element, "percentage", "0") or 0),
            battery_capacity=_distribution(element, "batteryCapacity", path, 0),
            initial_battery_level=_distribution(element, "initialBatteryLevel", path, 100),
            idle_consumption=_distribution(element, "idleConsumption", path, 0),
            max_consumption=_distribution(element, "maxConsumption", path, 0),
            orchestrator=_boolean(element, "isOrchestrator", False),
            generates_tasks=_boolean(element, "generateTasks", True),
            cores=_distribution(element, "cores", path, 1),
            mips=_distribution(element, "mips", path, 1000),
            ram=_distribution(element, "ram", path, 1000),
            storage=_distribution(element, "storage", path, 1000),
            x=_distribution(location, "x_pos", path, 0) if location is not None else None,
            y=_distribution(location, "y_pos", path, 0) if location is not None else None,
        ))
    if not specs:
        raise ValueError(f"{path}: no <device> element found")
    total = sum(spec.percentage for spec in specs)
    if round(total, 4) != 100:
        raise ValueError(f"{path}: device percentages must add up to 100, found {total}")
    for spec in specs:
        if spec.connectivity not in ("wifi", "cellular", "ethernet"):
            raise ValueError(f'{path}: unknown connectivity "{spec.connectivity}", '
                             'expected wifi, cellular, or ethernet')
    return specs


def load_settings(folder: str | Path) -> ScenarioFiles:
    folder = Path(folder)
    missing = [name for name in ("simulation_parameters.properties", "applications.xml", "cloud.xml",
                                 "edge_datacenters.xml", "edge_devices.xml") if not (folder / name).is_file()]
    if missing:
        raise FileNotFoundError(f"{folder}: missing settings file(s): {', '.join(missing)}")
    edge_specs, man_links = load_edge_datacenters(folder / "edge_datacenters.xml")
    return ScenarioFiles(
        applications=load_applications(folder / "applications.xml"),
        cloud=load_cloud(folder / "cloud.xml"),
        edge_datacenters=edge_specs,
        devices=load_devices(folder / "edge_devices.xml"),
        man_links=man_links,
        edge_device_count=len(edge_specs),
    )

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


def load_applications(path: Path) -> list[Application]:
    root = _root(path)
    applications: list[Application] = []
    for element in root.findall("application"):
        rate = _distribution(element, "rate", path)
        applications.append(Application(
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
        ))
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

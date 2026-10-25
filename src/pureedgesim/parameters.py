"""Global simulation parameters and the properties parser."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

NANOJOULES_TO_WATT_HOURS = 2.7777777777778e-13
CELLULAR_DOWNLINK_FACTOR = 12.7777777777778e-13
ARCHITECTURES = ("CLOUD_ONLY", "EDGE_ONLY", "MIST_ONLY", "MIST_AND_CLOUD", "EDGE_AND_CLOUD",
                 "MIST_AND_EDGE", "ALL")

# Every property the parser reads, used to point out unknown keys.
KNOWN_PROPERTIES = frozenset((
    "random_seed", "simulation_time", "batch_size", "parallel_simulation", "update_interval", "pause_length",
    "display_real_time_charts", "auto_close_real_time_charts", "charts_update_interval", "save_charts", "length",
    "width", "edge_devices_range", "edge_datacenters_coverage", "enable_registry", "registry_mode",
    "enable_orchestrators", "deploy_orchestrator", "wait_for_all_tasks", "save_log_file", "clear_output_folder",
    "deep_log_enabled", "min_number_of_edge_devices", "max_number_of_edge_devices", "edge_device_counter_size",
    "realistic_network_model", "network_update_interval", "one_shared_wan_network", "output_folder",
    "wan_bandwidth", "wan_latency", "wan_nanojoules_per_bit", "man_bandwidth", "man_latency",
    "man_nanojoules_per_bit", "wifi_bandwidth", "wifi_device_transmission_nanojoules_per_bit",
    "wifi_device_reception_nanojoules_per_bit", "wifi_access_point_transmission_nanojoules_per_bit",
    "wifi_access_point_reception_nanojoules_per_bit", "wifi_latency", "ethernet_bandwidth",
    "ethernet_nanojoules_per_bit", "ethernet_latency", "cellular_bandwidth",
    "cellular_device_transmission_nanojoules_per_bit", "cellular_device_reception_nanojoules_per_bit",
    "cellular_base_station_nanojoules_per_bit_up_link", "cellular_base_station_nanojoules_per_bit_down_link",
    "cellular_latency", "orchestration_architectures", "orchestration_algorithms",
))


@dataclass
class SimulationParameters:
    simulation_duration: float = 600.0
    update_interval: float = 1.0
    pause_length: float = 3.0
    batch_size: int = 100
    random_seed: int | None = None
    parallel_simulation: bool = False
    display_real_time_charts: bool = False
    auto_close_real_time_charts: bool = True
    charts_update_interval: float = 30.0
    save_charts: bool = False
    save_log_file: bool = True
    clear_output_folder: bool = False
    deep_log_enabled: bool = False
    simulation_map_length: float = 200.0
    simulation_map_width: float = 200.0
    edge_devices_range: float = 10.0
    edge_data_centers_range: float = 200.0
    enable_location_updates: bool = True
    enable_registry: bool = False
    registry_mode: str = "CLOUD"
    enable_orchestrators: bool = False
    deploy_orchestrator: str = "CLOUD"
    wait_for_all_tasks: bool = True
    min_number_of_devices: int = 100
    max_number_of_devices: int = 300
    devices_increment: int = 100
    realistic_network_model: bool = False
    network_update_interval: float = 1.0
    one_shared_wan_network: bool = True
    output_folder: str = "output"
    settings_folder: str = "settings"
    wan_bandwidth: float = 20e6
    wan_delay: float = 0.06
    wan_energy_per_bit: float = 46.7 * NANOJOULES_TO_WATT_HOURS
    man_bandwidth: float = 1000e6
    man_delay: float = 0.01
    man_energy_per_bit: float = 0.0
    wifi_bandwidth: float = 1300e6
    wifi_delay: float = 0.005
    wifi_device_transmission_energy: float = 283.17 * NANOJOULES_TO_WATT_HOURS
    wifi_device_reception_energy: float = 137.01 * NANOJOULES_TO_WATT_HOURS
    wifi_access_point_transmission_energy: float = 23.8 * NANOJOULES_TO_WATT_HOURS
    wifi_access_point_reception_energy: float = 23.8 * NANOJOULES_TO_WATT_HOURS
    ethernet_bandwidth: float = 1000e6
    ethernet_delay: float = 0.002
    ethernet_energy_per_bit: float = 40000 * NANOJOULES_TO_WATT_HOURS
    cellular_bandwidth: float = 100e6
    cellular_delay: float = 0.03
    cellular_device_transmission_energy: float = 438.4 * NANOJOULES_TO_WATT_HOURS
    cellular_device_reception_energy: float = 51.97 * NANOJOULES_TO_WATT_HOURS
    cellular_base_station_uplink_energy: float = 6200 * NANOJOULES_TO_WATT_HOURS
    cellular_base_station_downlink_energy: float = 20500 * CELLULAR_DOWNLINK_FACTOR
    orchestration_architectures: list[str] = field(default_factory=lambda: ["ALL"])
    orchestration_algorithms: list[str] = field(default_factory=lambda: ["TRADE_OFF"])

    @property
    def device_counts(self) -> list[int]:
        counts = []
        count = self.min_number_of_devices
        while count <= self.max_number_of_devices:
            counts.append(count)
            count += self.devices_increment
        return counts or [self.max_number_of_devices]


def _get(values: dict[str, str], key: str, path: Path) -> str:
    if key not in values:
        raise ValueError(f'missing parameter "{key}" in {path}')
    return values[key].strip()


def _number(values: dict[str, str], key: str, path: Path, default: float) -> float:
    if key not in values or values[key].strip() == "":
        return default
    try:
        return float(values[key].strip())
    except ValueError as error:
        raise ValueError(f'{path}: parameter "{key}" must be a number, found "{values[key].strip()}"') from error


def _boolean(values: dict[str, str], key: str, path: Path, default: bool) -> bool:
    if key not in values or values[key].strip() == "":
        return default
    value = values[key].strip()
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    hint = _suggestion(value, ("true", "false"))
    suffix = f', did you mean "{hint}"?' if hint else "."
    raise ValueError(f'{path}: parameter "{key}" must be "true" or "false", found "{value}"{suffix}')


def _suggestion(name: str, known) -> str | None:
    """The known name closest to the given one, when it differs by at most two edits."""
    def distance(first: str, second: str) -> int:
        previous = list(range(len(second) + 1))
        for i, first_char in enumerate(first, 1):
            current = [i]
            for j, second_char in enumerate(second, 1):
                current.append(min(previous[j] + 1, current[j - 1] + 1,
                                   previous[j - 1] + (first_char != second_char)))
            previous = current
        return previous[-1]

    best = min(known, key=lambda candidate: distance(name.lower(), candidate.lower()))
    return best if distance(name.lower(), best.lower()) <= 2 else None


def _warn_about_unknown_properties(values: dict[str, str], path: Path) -> None:
    """A misspelled key would otherwise be ignored silently, and the
    simulation would run with an unintended value."""
    for key in sorted(values):
        if key in KNOWN_PROPERTIES:
            continue
        hint = _suggestion(key, KNOWN_PROPERTIES)
        detail = f', did you mean "{hint}"?' if hint else ", it is ignored."
        print(f'{path}: warning, unknown property "{key}"{detail}', file=sys.stderr)


def load_parameters(path: str | Path) -> SimulationParameters:
    """Reads a PureEdgeSim simulation_parameters.properties file."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"parameters file not found: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if text == "" or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        values[key.strip()] = value

    parameters = SimulationParameters()
    _warn_about_unknown_properties(values, path)
    parameters.simulation_duration = _number(values, "simulation_time", path, 10) * 60
    parameters.update_interval = _number(values, "update_interval", path, 1)
    parameters.pause_length = _number(values, "pause_length", path, 3)
    parameters.batch_size = int(_number(values, "batch_size", path, 100))
    parameters.parallel_simulation = _boolean(values, "parallel_simulation", path, False)
    parameters.display_real_time_charts = _boolean(values, "display_real_time_charts", path, False)
    parameters.auto_close_real_time_charts = _boolean(values, "auto_close_real_time_charts", path, True)
    parameters.charts_update_interval = _number(values, "charts_update_interval", path, 30)
    parameters.save_charts = _boolean(values, "save_charts", path, False)
    parameters.save_log_file = _boolean(values, "save_log_file", path, True)
    parameters.clear_output_folder = _boolean(values, "clear_output_folder", path, False)
    parameters.deep_log_enabled = _boolean(values, "deep_log_enabled", path, False)
    parameters.simulation_map_length = _number(values, "length", path, 200)
    parameters.simulation_map_width = _number(values, "width", path, 200)
    parameters.edge_devices_range = _number(values, "edge_devices_range", path, 10)
    parameters.edge_data_centers_range = _number(values, "edge_datacenters_coverage", path, 200)
    parameters.enable_registry = _boolean(values, "enable_registry", path, False)
    parameters.registry_mode = _get(values, "registry_mode", path) if "registry_mode" in values else "CLOUD"
    parameters.enable_orchestrators = _boolean(values, "enable_orchestrators", path, False)
    parameters.deploy_orchestrator = (values.get("deploy_orchestrator") or "CLOUD").strip()
    parameters.wait_for_all_tasks = _boolean(values, "wait_for_all_tasks", path, True)
    parameters.min_number_of_devices = int(_number(values, "min_number_of_edge_devices", path, 100))
    parameters.max_number_of_devices = int(_number(values, "max_number_of_edge_devices", path, 300))
    parameters.devices_increment = int(_number(values, "edge_device_counter_size", path, 100))
    parameters.realistic_network_model = _boolean(values, "realistic_network_model", path, False)
    parameters.network_update_interval = _number(values, "network_update_interval", path, 1)
    parameters.one_shared_wan_network = _boolean(values, "one_shared_wan_network", path, True)
    parameters.output_folder = (values.get("output_folder") or "output").strip()
    seed = values.get("random_seed", "").strip()
    if seed:
        try:
            parameters.random_seed = int(float(seed))
        except ValueError as error:
            raise ValueError(f'{path}: "random_seed" must be a whole number, found "{seed}"') from error

    parameters.wan_bandwidth = _number(values, "wan_bandwidth", path, 20) * 1e6
    parameters.wan_delay = _number(values, "wan_latency", path, 0.06)
    parameters.wan_energy_per_bit = _number(values, "wan_nanojoules_per_bit", path, 46.7) * NANOJOULES_TO_WATT_HOURS
    parameters.man_bandwidth = _number(values, "man_bandwidth", path, 1000) * 1e6
    parameters.man_delay = _number(values, "man_latency", path, 0.01)
    parameters.man_energy_per_bit = _number(values, "man_nanojoules_per_bit", path, 0) * NANOJOULES_TO_WATT_HOURS
    parameters.wifi_bandwidth = _number(values, "wifi_bandwidth", path, 1300) * 1e6
    parameters.wifi_delay = _number(values, "wifi_latency", path, 0.005)
    parameters.wifi_device_transmission_energy = _number(
        values, "wifi_device_transmission_nanojoules_per_bit", path, 283.17) * NANOJOULES_TO_WATT_HOURS
    parameters.wifi_device_reception_energy = _number(
        values, "wifi_device_reception_nanojoules_per_bit", path, 137.01) * NANOJOULES_TO_WATT_HOURS
    parameters.wifi_access_point_transmission_energy = _number(
        values, "wifi_access_point_transmission_nanojoules_per_bit", path, 23.8) * NANOJOULES_TO_WATT_HOURS
    parameters.wifi_access_point_reception_energy = _number(
        values, "wifi_access_point_reception_nanojoules_per_bit", path, 23.8) * NANOJOULES_TO_WATT_HOURS
    parameters.ethernet_bandwidth = _number(values, "ethernet_bandwidth", path, 1000) * 1e6
    parameters.ethernet_delay = _number(values, "ethernet_latency", path, 0.002)
    parameters.ethernet_energy_per_bit = _number(
        values, "ethernet_nanojoules_per_bit", path, 40000) * NANOJOULES_TO_WATT_HOURS
    parameters.cellular_bandwidth = _number(values, "cellular_bandwidth", path, 100) * 1e6
    parameters.cellular_delay = _number(values, "cellular_latency", path, 0.03)
    parameters.cellular_device_transmission_energy = _number(
        values, "cellular_device_transmission_nanojoules_per_bit", path, 438.4) * NANOJOULES_TO_WATT_HOURS
    parameters.cellular_device_reception_energy = _number(
        values, "cellular_device_reception_nanojoules_per_bit", path, 51.97) * NANOJOULES_TO_WATT_HOURS
    parameters.cellular_base_station_uplink_energy = _number(
        values, "cellular_base_station_nanojoules_per_bit_up_link", path, 6200) * NANOJOULES_TO_WATT_HOURS
    parameters.cellular_base_station_downlink_energy = _number(
        values, "cellular_base_station_nanojoules_per_bit_down_link", path, 20500) * CELLULAR_DOWNLINK_FACTOR

    architectures = (values.get("orchestration_architectures") or "ALL").split(",")
    parameters.orchestration_architectures = [a.strip() for a in architectures if a.strip()]
    algorithms = (values.get("orchestration_algorithms") or "TRADE_OFF").split(",")
    parameters.orchestration_algorithms = [a.strip() for a in algorithms if a.strip()]
    validate(parameters, path)
    return parameters


def validate(parameters: SimulationParameters, path: Path) -> None:
    checks = (
        (parameters.simulation_duration > 0, "simulation_time must be > 0"),
        (parameters.update_interval >= 0.01, "update_interval must be >= 0.01"),
        (parameters.pause_length >= 0, "pause_length must be >= 0"),
        (parameters.batch_size > 0, "batch_size must be > 0"),
        (parameters.simulation_map_length > 0, "length must be > 0"),
        (parameters.simulation_map_width > 0, "width must be > 0"),
        (parameters.edge_devices_range > 0, "edge_devices_range must be > 0"),
        (parameters.edge_data_centers_range > 0, "edge_datacenters_coverage must be > 0"),
        (parameters.min_number_of_devices > 0, "min_number_of_edge_devices must be > 0"),
        (parameters.max_number_of_devices >= parameters.min_number_of_devices,
         "max_number_of_edge_devices must be >= min_number_of_edge_devices"),
        (parameters.devices_increment > 0, "edge_device_counter_size must be > 0"),
        (parameters.network_update_interval >= 0.001, "network_update_interval must be >= 0.001"),
        (0.01 <= parameters.charts_update_interval <= 60, "charts_update_interval must be between 0.01 and 60"),
        (parameters.registry_mode in ("CLOUD", "CACHE"), 'registry_mode must be "CLOUD" or "CACHE"'),
        (bool(parameters.orchestration_algorithms), "orchestration_algorithms must not be empty"),
    )
    for ok, message in checks:
        if not ok:
            raise ValueError(f"{path}: {message}")
    for architecture in parameters.orchestration_architectures:
        if architecture not in ARCHITECTURES:
            raise ValueError(f'{path}: unknown architecture "{architecture}", expected one of {", ".join(ARCHITECTURES)}')

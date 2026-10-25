"""Runs the scenario sweep and writes the results, the counterpart of Simulation."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .config import ScenarioFiles, load_settings
from .engine import Engine
from .manager import Scenario, SimulationManager
from .metadata import write_run_metadata
from .network import LinkTechnology, LinkType
from .parameters import SimulationParameters, load_parameters
from .randomness import Randomness

COLUMNS = [
    "Orchestration architecture", "Orchestration algorithm", "Edge devices count",
    "Total tasks execution delay (s)", "Average execution delay (s)", "Total tasks waiting time (s)",
    "Average waiting time (s)", "Number of generated tasks", "Tasks successfully executed",
    "Task not executed (No resources available or long waiting time)", "Tasks failed (delay)",
    "Tasks failed (device dead)", "Tasks failed (mobility)",
    "Tasks not generated due to the death of devices", "Total tasks executed (Cloud)",
    "Successful tasks executed (Cloud)", "Total tasks executed (Edge)", "Successful tasks executed (Edge)",
    "Total tasks executed (Mist)", "Successful tasks executed (Mist)", "Network usage (s)", "Wan usage (s)",
    "Lan usage (s)", "Total network traffic (MBytes)", "Containers wan usage (s)", "Containers lan usage (s)",
    "Average bandwidth per task (Mbps)", "Average CPU usage (%)", "Average CPU usage (Cloud) (%)",
    "Average CPU usage (Edge) (%)", "Average CPU usage (Mist) (%)",
    "Energy consumption of computing nodes (Wh)", "Average energy consumption (Wh/Computing node)",
    "Cloud energy consumption (Wh)", "Average Cloud energy consumption (Wh/Data center)",
    "Edge energy consumption (Wh)", "Average Edge energy consumption (Wh/Data center)",
    "Mist energy consumption (Wh)", "Average Mist energy consumption (Wh/Device)",
    "WAN energy consumption (Wh)", "MAN energy consumption (Wh)", "LAN energy consumption (Wh)",
    "WiFi energy consumption (Wh)", "LTE energy consumption (Wh)", "Ethernet energy consumption (Wh)",
    "Dead devices count", "Average remaining power (Wh)", "Average remaining power (%)",
    "First edge device death time (s)",
    "List of remaining power (%) (only battery powered devices / 0 = dead)",
    "List of the time when each device died (s)",
]


def build_scenarios(parameters: SimulationParameters) -> list[Scenario]:
    return [Scenario(architecture, algorithm, count)
            for architecture in parameters.orchestration_architectures
            for algorithm in parameters.orchestration_algorithms
            for count in parameters.device_counts]


def run_scenario(parameters: SimulationParameters, files: ScenarioFiles, scenario: Scenario,
                 iteration: int, custom_mobility_model=None, custom_orchestrator=None) -> dict:
    """One iteration: a fresh engine, a fresh manager, one result row."""
    # The seed travels with the parameters, so a worker process derives the same
    # stream as the main thread, like the static field does in PureEdgeSim.
    Randomness.set_seed(parameters.random_seed)
    Randomness.begin_scenario(iteration)
    engine = Engine(parameters.simulation_duration)
    manager = SimulationManager(engine, parameters, files, scenario, custom_mobility_model, custom_orchestrator)
    manager.start_simulation()
    engine.start()
    return summarize(manager)


def _round(value: float, digits: int = 4) -> float:
    if value != value or value in (float("inf"), float("-inf")):
        return value
    return round(value, digits)


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _energy_of(nodes) -> float:
    return sum(node.energy_model.get_total_energy_consumption() for node in nodes)


def _cpu_of(nodes) -> float:
    return _average([node.get_cpu_usage_average() for node in nodes])


def summarize(manager: SimulationManager) -> dict:
    metrics = manager.metrics
    network = manager.network
    devices = manager.edge_devices
    cloud = manager.nodes_generator.cloud_nodes
    edge = manager.nodes_generator.edge_data_centers
    executed = metrics.executed_tasks
    battery_devices = [node for node in devices if node.is_battery_powered()]
    alive_battery = [node for node in battery_devices if node.is_alive()]
    dead_devices = [node for node in devices if node.is_dead()]
    data_centers = len(cloud) + len(edge)
    row = {
        COLUMNS[0]: manager.scenario.orchestration_architecture,
        COLUMNS[1]: manager.scenario.orchestration_algorithm,
        COLUMNS[2]: manager.scenario.devices_count,
        COLUMNS[3]: _round(metrics.total_execution_time),
        COLUMNS[4]: _round(metrics.total_execution_time / executed if executed else 0.0),
        COLUMNS[5]: _round(metrics.total_waiting_time),
        COLUMNS[6]: _round(metrics.total_waiting_time / executed if executed else 0.0),
        COLUMNS[7]: metrics.generated_tasks,
        COLUMNS[8]: metrics.succeeded_tasks,
        COLUMNS[9]: metrics.not_executed,
        COLUMNS[10]: metrics.delay_failures,
        COLUMNS[11]: metrics.death_failures,
        COLUMNS[12]: metrics.mobility_failures,
        # PureEdgeSim never increments this counter: tasks are all generated
        # before the simulation starts, so no task is lost to a dead device.
        COLUMNS[13]: metrics.not_generated,
        COLUMNS[14]: metrics.cloud_tasks,
        COLUMNS[15]: metrics.cloud_successes,
        COLUMNS[16]: metrics.edge_tasks,
        COLUMNS[17]: metrics.edge_successes,
        COLUMNS[18]: metrics.mist_tasks,
        COLUMNS[19]: metrics.mist_successes,
        # PureEdgeSim writes the LAN usage in this column while its text report
        # prints LAN+MAN+WAN; the CSV is kept compatible with the Java output.
        COLUMNS[20]: _round(sum(network.network_usage.values())),
        COLUMNS[21]: _round(network.network_usage[LinkType.WAN]),
        COLUMNS[22]: _round(network.network_usage[LinkType.LAN]),
        COLUMNS[23]: _round(network.total_traffic_bits / 8 / 1e6),
        COLUMNS[24]: _round(network.container_usage[LinkType.WAN]),
        COLUMNS[25]: _round(network.container_usage[LinkType.LAN]),
        COLUMNS[26]: _round(network.get_average_bandwidth_per_task()),
        COLUMNS[27]: _round(_average([node.get_cpu_usage_average() for node in manager.computing_nodes
                                      if not node.is_sensor])),
        COLUMNS[28]: _round(_cpu_of([node for node in cloud if not node.is_sensor])),
        COLUMNS[29]: _round(_cpu_of([node for node in edge if not node.is_sensor])),
        COLUMNS[30]: _round(_cpu_of([node for node in devices if not node.is_sensor])),
        COLUMNS[31]: _round(_energy_of(cloud) + _energy_of(edge) + _energy_of(devices)),
        COLUMNS[32]: _round((_energy_of(cloud) + _energy_of(edge) + _energy_of(devices))
                            / (data_centers + len(devices)) if (data_centers + len(devices)) else 0.0),
        COLUMNS[33]: _round(_energy_of(cloud)),
        COLUMNS[34]: _round(_energy_of(cloud) / len(cloud) if cloud else 0.0),
        COLUMNS[35]: _round(_energy_of(edge)),
        COLUMNS[36]: _round(_energy_of(edge) / len(edge) if edge else 0.0),
        COLUMNS[37]: _round(_energy_of(devices)),
        COLUMNS[38]: _round(_energy_of(devices) / len(devices) if devices else 0.0),
        COLUMNS[39]: _round(network.link_energy[LinkType.WAN]),
        COLUMNS[40]: _round(network.link_energy[LinkType.MAN]),
        COLUMNS[41]: _round(network.link_energy[LinkType.LAN]),
        COLUMNS[42]: _round(network.technology_energy[LinkTechnology.WIFI]),
        COLUMNS[43]: _round(network.technology_energy[LinkTechnology.CELLULAR]),
        COLUMNS[44]: _round(network.technology_energy[LinkTechnology.ETHERNET]),
        COLUMNS[45]: metrics.dead_devices,
        COLUMNS[46]: _round(_average([node.get_remaining_battery() for node in alive_battery])),
        COLUMNS[47]: _round(_average([node.get_remaining_battery_percentage() for node in alive_battery])),
        COLUMNS[48]: _round(min((node.death_time for node in dead_devices), default=-1.0)),
        COLUMNS[49]: "-".join(str(round(node.get_remaining_battery_percentage(), 2)) if node.is_alive() else "0"
                              for node in battery_devices),
        COLUMNS[50]: "-".join(str(round(node.death_time, 2)) for node in dead_devices),
    }
    return row


def output_folder(base: str | Path, timestamp: str | None = None) -> Path:
    folder = Path(base)
    return folder / (timestamp or datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))


class Simulation:
    def __init__(self, settings_folder: str | Path = "settings", output_folder: str | Path | None = None,
                 parameters: SimulationParameters | None = None, files: ScenarioFiles | None = None) -> None:
        self.settings_folder = Path(settings_folder)
        self.output_folder = Path(output_folder) if output_folder else None
        self.parameters = parameters
        self.files = files
        self.custom_mobility_model = None
        self.custom_orchestrator = None

    def set_custom_mobility_model(self, model) -> "Simulation":
        self.custom_mobility_model = model
        return self

    def set_custom_orchestrator(self, orchestrator) -> "Simulation":
        self.custom_orchestrator = orchestrator
        return self

    def load(self) -> None:
        if self.parameters is None:
            self.parameters = load_parameters(self.settings_folder / "simulation_parameters.properties")
        if self.files is None:
            self.files = load_settings(self.settings_folder)
        if self.output_folder is None:
            self.output_folder = Path(self.parameters.output_folder)

    def launch(self) -> list[dict]:
        self.load()
        Randomness.set_seed(self.parameters.random_seed)
        scenarios = build_scenarios(self.parameters)
        if self.parameters.clear_output_folder:
            self._clean_output_folder()
        folder = output_folder(self.output_folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.results_folder = folder
        write_run_metadata(self.settings_folder, folder, self.parameters.parallel_simulation,
                           self.parameters.random_seed)
        csv_path = folder / ("Parallel_simulation.csv" if self.parameters.parallel_simulation
                             else "Sequential_simulation.csv")
        if self.parameters.parallel_simulation:
            rows = self._run_parallel(scenarios, csv_path)
        else:
            rows = []
            for iteration, scenario in enumerate(scenarios):
                rows.append(run_scenario(self.parameters, self.files, scenario, iteration,
                                         self.custom_mobility_model, self.custom_orchestrator))
                _append_row(csv_path, rows[-1])
        if self.parameters.save_log_file:
            name = "Parallel_simulation.txt" if self.parameters.parallel_simulation else "Sequential_simulation.txt"
            (folder / name).write_text("\n\n".join(_text_report(row) for row in rows), encoding="utf-8")
        return rows

    def _clean_output_folder(self) -> None:
        """Deletes the previous results, the counterpart of cleanOutputFolder."""
        import shutil

        folder = self.output_folder
        if folder.exists() and folder.resolve() != Path.cwd().resolve():
            shutil.rmtree(folder)

    def _run_parallel(self, scenarios: list[Scenario], csv_path: Path) -> list[dict]:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=min(8, len(scenarios))) as pool:
            futures = [pool.submit(run_scenario, self.parameters, self.files, scenario, iteration,
                                   self.custom_mobility_model, self.custom_orchestrator)
                       for iteration, scenario in enumerate(scenarios)]
            rows = [future.result() for future in futures]
        for row in rows:
            _append_row(csv_path, row)
        return rows


def _append_row(path: Path, row: dict) -> None:
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _text_report(row: dict) -> str:
    lines = [f"Scenario: {row[COLUMNS[0]]} / {row[COLUMNS[1]]} / {row[COLUMNS[2]]} devices",
             f"  Generated tasks      : {row[COLUMNS[7]]}",
             f"  Successful tasks     : {row[COLUMNS[8]]}",
             f"  Failed (delay)       : {row[COLUMNS[10]]}",
             f"  Failed (death)       : {row[COLUMNS[11]]}",
             f"  Failed (mobility)    : {row[COLUMNS[12]]}",
             f"  Not executed         : {row[COLUMNS[9]]}",
             f"  Average delay (s)    : {row[COLUMNS[4]]}",
             f"  Average CPU (%)      : {row[COLUMNS[27]]}",
             f"  Energy (Wh)          : {row[COLUMNS[31]]}",
             f"  Dead devices         : {row[COLUMNS[45]]}"]
    return "\n".join(lines)

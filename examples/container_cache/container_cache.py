"""Storage-aware container caching at the edge: an LRU cache per computing node.

    python examples/container_cache/container_cache.py

Port of the Java `Example21CacheDevice` and `Example21ContainerCacheNetworkModel`.
Every node dedicates a few megabytes of its storage to application containers.
A request whose container is already there runs immediately; a request whose
container is missing downloads it from the registry first, and the downloaded
container is kept for the next request until the budget is full and the least
recently used container is evicted.

The Python core has no hook for a custom network model or a custom computing
node, so the behaviour lives in a `SimulationManager` subclass: the download
decision is taken in `_needs_container` and the container is stored when the
download has finished, exactly where the Java model hooks `transferFinished`.
"""
from __future__ import annotations

import csv
from pathlib import Path

from pureedgesim import (COLUMNS, Engine, NodeType, Randomness, Scenario, SimulationManager,
                         load_parameters, load_settings, summarize)
from pureedgesim.metadata import write_run_metadata
from pureedgesim.runner import output_folder as results_folder

SETTINGS = Path(__file__).resolve().parent / "settings"
OUTPUT = "examples/container_cache/output"
CACHE_CAPACITY_MB = 3.0
CSV_NAME = "Sequential_simulation.csv"
CSV_FIELDS = list(COLUMNS)


class ContainerCache:
    """A least-recently-used cache of application containers, bounded in megabytes."""

    def __init__(self, capacity_mb: float) -> None:
        self.capacity_mb = max(0.0, float(capacity_mb))
        # A plain dict keeps the insertion order, and a hit moves the container to
        # the end, so the first key is always the least recently used one.
        self._containers: dict[int, float] = {}
        self.used_mb = 0.0
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.rejected = 0

    def lookup(self, application_id: int) -> bool:
        """Counts the request and refreshes the access order of a present container."""
        if application_id in self._containers:
            self._containers[application_id] = self._containers.pop(application_id)
            self.hits += 1
            return True
        self.misses += 1
        return False

    def contains(self, application_id: int) -> bool:
        return application_id in self._containers

    def store(self, application_id: int, size_mb: float) -> bool:
        """Stores a container, evicting the least recently used until it fits."""
        if size_mb > self.capacity_mb:
            self.rejected += 1
            return False
        previous = self._containers.pop(application_id, None)
        if previous is not None:
            self.used_mb -= previous
        while self._containers and self.used_mb + size_mb > self.capacity_mb:
            eldest = next(iter(self._containers))
            self.used_mb -= self._containers.pop(eldest)
            self.evictions += 1
        self._containers[application_id] = size_mb
        self.used_mb += size_mb
        return True

    def size(self) -> int:
        return len(self._containers)

    @property
    def hit_ratio(self) -> float:
        requests = self.hits + self.misses
        return self.hits / requests if requests else 0.0


class ContainerCacheSimulationManager(SimulationManager):
    """Gives every node a container cache and consults it before a download."""

    def __init__(self, engine, parameters, files, scenario, cache_capacity_mb: float = CACHE_CAPACITY_MB) -> None:
        super().__init__(engine, parameters, files, scenario)
        self.cache_capacity_mb = cache_capacity_mb
        self.container_caches: dict[int, ContainerCache] = {}
        self.pending_store: dict[int, tuple[ContainerCache, int, float]] = {}
        self.cache_enabled = parameters.enable_registry and parameters.registry_mode == "CACHE"

    def start_simulation(self) -> None:
        super().start_simulation()
        if not self.cache_enabled:
            return
        for node in self.computing_nodes:
            # A node never reserves more than it has, and a sensor has no storage.
            if node.type is not NodeType.CLOUD and not node.is_sensor:
                self.container_caches[node.id] = ContainerCache(
                    min(self.cache_capacity_mb, node.available_storage))

    def _needs_container(self, task, destination) -> bool:
        if not self.cache_enabled:
            return super()._needs_container(task, destination)
        if destination.type is NodeType.CLOUD:
            return False
        cache = self.container_caches.get(destination.id)
        if cache is None:
            return True
        if cache.lookup(task.application_id):
            return False
        self.pending_store[task.id] = (cache, task.application_id, destination.get_container_mb(task))
        return True

    def _send_request_to_destination(self, task, destination, callback) -> None:
        entry = self.pending_store.pop(task.id, None)
        if entry is not None:
            cache, application_id, size_mb = entry
            cache.store(application_id, size_mb)
        super()._send_request_to_destination(task, destination, callback)

    def cache_report(self) -> str:
        hits = sum(cache.hits for cache in self.container_caches.values())
        misses = sum(cache.misses for cache in self.container_caches.values())
        evictions = sum(cache.evictions for cache in self.container_caches.values())
        rejected = sum(cache.rejected for cache in self.container_caches.values())
        used = sum(cache.used_mb for cache in self.container_caches.values())
        capacity = sum(cache.capacity_mb for cache in self.container_caches.values())
        requests = hits + misses
        ratio = 100.0 * hits / requests if requests else 0.0
        return (f"container cache: {hits} hits, {misses} misses ({ratio:.2f} % hit ratio), "
                f"{evictions} evictions, {rejected} refused, "
                f"{used:.2f} MB used of {capacity:.2f} MB")

    def on_simulation_end(self) -> None:
        if self.cache_enabled:
            print(f"ContainerCache - {self.cache_report()}")


class UncachedRegistryManager(SimulationManager):
    """The Java baseline: `registry_mode=CLOUD` downloads a container per request.

    The Python core remembers every downloaded container in
    `destination.installed_containers` and never downloads it twice, which is an
    unbounded cache. This subclass drops that memory so the cached run can be
    compared with a run that really pays for every download.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # The interface of the cached manager, switched off: the two runs differ
        # by one flag, and the reports can ask either manager for its caches.
        self.cache_enabled = False
        self.container_caches: dict[int, ContainerCache] = {}

    def _needs_container(self, task, destination) -> bool:
        if (self.parameters.enable_registry and self.parameters.registry_mode == "CLOUD"
                and destination.type is not NodeType.CLOUD):
            return True
        return super()._needs_container(task, destination)


MANAGERS = {
    "cache": ContainerCacheSimulationManager,
    "cloud": SimulationManager,
    "cloud_always": UncachedRegistryManager,
}


def build_manager(mode: str, parameters, files, scenario):
    Randomness.set_seed(parameters.random_seed)
    Randomness.begin_scenario(0)
    engine = Engine(parameters.simulation_duration)
    manager = MANAGERS[mode](engine, parameters, files, scenario)
    manager.start_simulation()
    return engine, manager


def run(mode: str = "cache", devices: int | None = None, duration: float | None = None,
        seed: int | None = None, output: str | Path = OUTPUT,
        folder: str | Path | None = None) -> dict:
    """Runs one scenario and appends its row to the results CSV of `folder`."""
    parameters = load_parameters(SETTINGS / "simulation_parameters.properties")
    if mode in ("cloud", "cloud_always"):
        parameters.registry_mode = "CLOUD"
    if devices is not None:
        parameters.min_number_of_devices = parameters.max_number_of_devices = devices
        parameters.devices_increment = 1
    if duration is not None:
        parameters.simulation_duration = duration
    if seed is not None:
        parameters.random_seed = seed
    scenario = Scenario(parameters.orchestration_architectures[0], parameters.orchestration_algorithms[0],
                        parameters.max_number_of_devices)
    engine, manager = build_manager(mode, parameters, load_settings(SETTINGS), scenario)
    engine.start()
    row = summarize(manager)
    folder = Path(folder) if folder else results_folder(output)
    folder.mkdir(parents=True, exist_ok=True)
    write_run_metadata(SETTINGS, folder, parameters.parallel_simulation, parameters.random_seed)
    path = folder / CSV_NAME
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    print(f"{mode:<13} tasks={row[COLUMNS[7]]:>6} ok={row[COLUMNS[8]]:>6} "
          f"success={_percent(row[COLUMNS[8]], row[COLUMNS[7]]):>6} avg_delay={row[COLUMNS[4]]:<8} "
          f"wan_usage={row[COLUMNS[22]]:<12} containers_lan={row[COLUMNS[26]]:<8} "
          f"traffic_MB={row[COLUMNS[24]]:<10} energy={row[COLUMNS[32]]}")
    return row


def _percent(part: int, total: int) -> str:
    return f"{100.0 * part / total:.2f} %" if total else "0.00 %"


def main(devices: int | None = None, duration: float | None = None, seed: int | None = None,
         output: str | Path = OUTPUT) -> list[dict]:
    """Runs the three container handlings on the same seed and workload."""
    print("registry mode / container handling (same seed, same workload, same architecture)")
    # One timestamped folder, three rows: the three handlings of the same workload
    # belong in a single CSV, the way a Java sequential run writes its scenarios.
    folder = results_folder(output)
    return [run(mode, devices, duration, seed, output, folder) for mode in ("cache", "cloud_always", "cloud")]


if __name__ == "__main__":
    main()

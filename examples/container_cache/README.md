# Container caching: keeping the image where the task runs

## What it shows

An edge node that runs an application needs that application's container
installed first, and pulling it over the network is expensive. `CACHE` mode
answers this with a small storage-aware cache: every node reserves a few
megabytes of its storage for containers, a request whose container is already
there runs without a download, and a request whose container is missing fetches
it once and keeps it for the next request. When the budget is full the least
recently used container is evicted.

The Python core has no hook for a custom network model or a custom computing
node, so the behaviour lives in `ContainerCacheSimulationManager`, a subclass of
`SimulationManager`. On a placement it calls `_needs_container`, which consults
the destination cache: a hit returns false and skips the transfer, a miss
remembers the container in `pending_store`. When the download has finished,
`_send_request_to_destination` stores it, evicting the oldest entries until the
new one fits, or refusing it if it is larger than the whole cache. A plain
`dict` keeps the access order, and a lookup moves the container to the end, so
the first key is always the least recently used one.

The point of the example is that the bounded cache is a middle ground, so the
script runs the same workload three times on the same seed, differing by one
flag:

- `cache`, the LRU cache described above;
- `cloud_always`, `UncachedRegistryManager` with `registry_mode=CLOUD`, which
  downloads a container for every single request, the honest baseline;
- `cloud`, the plain `SimulationManager`, which remembers every downloaded
  container forever, an unbounded cache nobody would pay for in production.

```mermaid
flowchart TD
    req["Task placed on a node"] --> look{"Container in the LRU cache?"}
    look -->|Hit| run["Run now, no download"]
    look -->|Miss| dl["Download from the registry"]
    dl --> fits{"Container plus used space fits 3 MB?"}
    fits -->|Yes| keep["Keep the container, then run"]
    fits -->|No, over capacity| refuse["Refuse, download again next time"]
    fits -->|No, but it can| evict["Evict least recently used until it fits"]
    evict --> keep
    keep --> run
    refuse --> run
    classDef cost fill:#ffe0b3,stroke:#333;
    class dl,evict,refuse cost;
```

## The scenario

`settings/` sets up one scenario:

- 300 devices on a 2000 by 2000 meters map, a 20 meters device-to-device range,
  seed 61, five simulated minutes;
- four peripheral edge data centers, each 10 cores at 40000 MIPS and 200000 MB
  of storage, linked in a ring over the MAN;
- the `EDGE_ONLY` architecture, so every offloaded task runs on the edge and the
  cloud is never a destination;
- a cloud orchestrator (`deploy_orchestrator=CLOUD`), so each request crosses
  the 20 Mbps WAN to the cloud and back even though the cloud computes nothing;
- the registry enabled in `CACHE` mode, and the three default applications whose
  containers weigh 0.02 MB (Health, Hard Real-time, 20 ms), 1.5 MB (Augmented
  reality, Soft Real-time, 0.5 s) and 2.2 MB (HEAVY_COMP_APP, Non Real-time).

`CACHE_CAPACITY_MB` is 3.0, so a node can hold the two heavy containers
together but not all three, which forces real evictions. A node never reserves
more than its own storage, and a sensor has no storage, so only the four data
centers and the 120 battery or mains devices get a cache.

## Run it

From the repository root, after `pip install -e .`:

```bash
python examples/container_cache/container_cache.py
```

No-install variant:

```bash
PYTHONPATH=src python examples/container_cache/container_cache.py
```

## What to look for

The run prints a header line, then the cache report, then the three rows:

```text
registry mode / container handling (same seed, same workload, same architecture)
ContainerCache - container cache: 10492 hits, 6378 misses (62.19 % hit ratio), 1308 evictions, 0 refused, 8.12 MB used of 372.00 MB
cache         tasks= 16870 ok=  1770 success=10.49 % avg_delay=0.1599   wan_usage=525137.076   containers_lan=0.0      traffic_MB=50294.24   energy=75.6774
cloud_always  tasks= 16870 ok=  1684 success=9.98 % avg_delay=0.1599   wan_usage=733151.644   containers_lan=0.0      traffic_MB=62212.0    energy=75.6774
cloud         tasks= 16870 ok=  1770 success=10.49 % avg_delay=0.1599   wan_usage=468487.352   containers_lan=0.0      traffic_MB=42505.72   energy=75.6774
```

All three rows carry the same workload and the same average execution delay, so the
columns that move are the container traffic, the request makespan, the network
energy, and, for the always-download baseline, the success count.

| Container handling | Total traffic (MB) | Container WAN time (s) | Request makespan (s) |
| --- | --- | --- | --- |
| LRU cache (`cache`) | 50294.24 | 178701.912 | 0.9976 |
| Download every request (`cloud_always`) | 62212.00 | 445211.112 | 1.0463 |
| Never evict (`cloud`) | 42505.72 | 391.024 | 1.0212 |

- The cache turns 10492 of the 16870 requests into a hit, a 62.19 percent hit
  ratio, and evicts 1308 containers to stay inside the 3 MB budget. The 372 MB
  total capacity is 124 nodes times 3 MB, so nothing is refused (0 refused): the
  largest container, 2.2 MB, always fits on its own.
- Against the download-every-request baseline the cache removes 19.2 percent of
  the traffic (62212.00 down to 50294.24 MB) and 59.9 percent of the container
  transfer time (445211.112 down to 178701.912 s of WAN). The never-evict baseline
  shows the ceiling, 42505.72 MB, so the bounded cache captures most but not all of
  the savings.
- The honest cost: in this port the container download is charged to the request
  makespan and the traffic, not to the task compute latency, so all three rows
  report the identical average execution delay of 0.1599 s. What the download path
  does change is the makespan and the success count. Against the always-download
  baseline the cache shortens the request makespan from 1.0463 to 0.9976 s (4.7
  percent) and lifts the success rate from 9.98 percent (1684 of 16870) to 10.49
  percent (1770), because saturating the shared WAN with a download on every
  request pushes the slowest tasks past their deadline. The computing-node energy
  is the same 75.6774 Wh in all three rows; only the network column moves, the WAN
  drawing 20.6285 Wh under always-download against 19.3917 Wh with the cache and
  18.5834 Wh when nothing is evicted.
- The low success rate is the scenario, not the cache: a cloud orchestrator sends
  every hard real-time Health task over the 20 Mbps WAN twice, which blows its
  20 ms budget regardless of how the container is handled. The WAN column, about
  468000 to 733000 s, now tracks the container handling rather than staying flat,
  because after the network model fix the registry pull travels the shared WAN (the
  one edge data center, `dc1`, that hangs on the WAN router) and the container LAN
  column reads 0.0 s in all three rows. Container downloads therefore book WAN time
  and WAN energy, not the MAN between the data centers, which is why the
  always-download row pays both the largest WAN time (733151.644 s) and the
  smallest number of successes.

Lower `CACHE_CAPACITY_MB` toward 1.5 to make the heavy 2.2 MB container
refusable, or raise it above 3.7 to let every node hold all three and watch the
evictions drop to zero.

Results go to `examples/container_cache/output/`.

## Files

- `container_cache.py` with `ContainerCache`, the cached manager, the uncached
  baseline and the three-way `main`
- `settings/` with `simulation_parameters.properties`, `applications.xml`,
  `edge_devices.xml`, `edge_datacenters.xml` and `cloud.xml`

## Where to go next

- [Clustering and caching](../clustering_and_caching/README.md) for a policy
  that both clusters devices and caches their containers
- [Fog layers](../fog_layers/README.md) for a placement that fills the mist
  before overflowing to the edge

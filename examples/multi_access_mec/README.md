# Multi-access MEC: the radio you talk over shapes the placement

## What it shows

The same task does not cost the same on the same node depending on how it got
there. A cellular smartphone pays 30 ms and a 100 Mbps uplink; a Wi-Fi tablet
pays 5 ms and 1300 Mbps. `AccessAwareOrchestrator` folds that difference into
the decision: it scores every allowed candidate as an estimated delay, and the
lowest score wins.

For a candidate node the score is the compute delay on that node, plus the access
delay of the link the task came in on, plus a queue term. The access delay is
the uplink transfer of the device's own technology (cellular or Wi-Fi), and a
cloud candidate pays the WAN hop on top of it. The compute delay is the task
length divided by the node's MIPS per core. The queue term charges one waiting
task for its share of the node's cores, so a busy edge server looks slower than
an idle one. The access technology enters only through that first term, but it
is enough to move a decision: a cellular device whose slow uplink dominates can
find it cheaper to hand the task to a nearby fast laptop on the direct Wi-Fi
link, while a Wi-Fi device, whose uplink to the edge is already fast, keeps the
edge.

```mermaid
flowchart LR
    Sm["120 smartphones<br/>cellular, 5000 MIPS"] --> Ce["Cellular uplink<br/>100 Mbps, 30 ms"]
    Tb["90 tablets<br/>Wi-Fi, 8000 MIPS"] --> Wi["Wi-Fi uplink<br/>1300 Mbps, 5 ms"]
    Lp["90 laptops<br/>Wi-Fi, 20000 MIPS"] --> Wi
    Ce --> Sc["Score each tier<br/>access + compute + queue / cores"]
    Wi --> Sc
    Sc --> Ed["Edge, 4 DCs<br/>16 cores, 60000 MIPS"]
    Sc --> Mi["Mist devices"]
    Sc --> Cl["Cloud<br/>WAN 20 Mbps, 60 ms"]
    classDef score fill:#cfe8ff,stroke:#333;
    class Sc score;
```

## The scenario

`settings/` sets up a multi-access cell:

- four edge data centers at the corners of a 2000 by 2000 meters map, each 16
  cores at 60000 MIPS, linked in a ring over the MAN, with a 1200 meters
  coverage;
- 300 devices, all thin clients that both generate and execute: 40 percent
  cellular smartphones (8 cores at 5000 MIPS, mobile), 30 percent Wi-Fi tablets
  (8 cores at 8000 MIPS) and 30 percent mains-powered Wi-Fi laptops (8 cores at
  20000 MIPS);
- the `ALL` architecture and the `ACCESS_AWARE` algorithm, ten simulated minutes,
  seed 42, decisions made on the device (`enable_orchestrators=false`), no
  registry, a 20 meters device-to-device range;
- a 20 Mbps WAN with 60 ms latency and a 100 Mbps cellular uplink with 30 ms,
  against 1300 Mbps and 5 ms for Wi-Fi;
- the three default applications, Health (20 percent), Augmented reality (30
  percent) and HEAVY_COMP_APP (50 percent).

## Run it

From the repository root, after `pip install -e .`:

```bash
python examples/multi_access_mec/multi_access_mec.py
```

No-install variant:

```bash
PYTHONPATH=src python examples/multi_access_mec/multi_access_mec.py
```

## What to look for

The console ends with the per-technology placements and the result row:

```text
AccessAwareOrchestrator - placements by access technology and tier: cellular/edge=4420, cellular/mist=225, wifi/edge=180
ACCESS_AWARE     devices= 300 tasks= 43500 ok= 38900 failed(delay)= 4600 avg_delay=0.107    cloud=   0 edge=42973 mist= 527 wan_usage=0.0       energy=179.5285
```

| Access technology | Placements on the edge | Placements on the mist |
| --- | --- | --- |
| cellular | 4420 | 225 |
| Wi-Fi | 180 | 0 |

- Both technologies overwhelmingly choose the edge, so the tier balance, 42973
  tasks executed on the edge against 527 on the mist, is dominated by edge data
  centers being fast and Wi-Fi devices being within reach. No task runs on the
  cloud, because the 20 Mbps plus 60 ms WAN term is added to every cloud estimate
  and keeps it above the edge and mist alternatives. The result row reports
  `wan_usage=0.0` and 0.0 Wh of MAN energy: the metro router to cloud hop is typed
  IGNORE, so it delays a task but moves no usage or energy counter, and the only
  edge data center hanging on that router is `dc1`, so the device to edge traffic
  runs over the Wi-Fi and LTE access links and lands on the LAN, which carries
  2184.2456 s of the 2187.48 s of total network usage and all of the network
  energy.
- The access-aware distinction lives in the mist column. Cellular devices reach
  the mist 225 times out of 4645 placements, about 4.8 percent, while Wi-Fi
  devices never do, 0 out of 180. A slow cellular uplink inflates the edge
  estimate, so a nearby fast laptop on the direct Wi-Fi link wins, an outcome a
  Wi-Fi device, whose own uplink to the edge is already fast, does not see.
- The cellular traffic dominates the radio bill even though it is only 40 percent
  of the devices: 558.2126 Wh of LTE network energy against 20.1575 Wh of Wi-Fi,
  which is what the 100 Mbps and 30 ms link costs to push the same bytes. The
  compute energy, 106.781 Wh mist and 72.7475 Wh edge, sums to the 179.5285 Wh
  reported for computing nodes.
- The load pressure the other fog examples show no longer breaks the run. The
  fleet generates 43500 requests and 38900 succeed, 89.43 percent, with only 4600
  missing their latency budget; the average compute time is 0.107 s and the
  average request makespan 0.1486 s. Transfers that used to be rounded up to the
  next one-second poll no longer push a task over its budget, so the four edge
  servers absorb the 300-device load at 11.525 percent average edge CPU usage
  instead of backing up.

Set `cellular_bandwidth` to 10 to widen the gap: cellular tasks pay ten times the
uplink transfer, more of them fall to a mist node, and the delay-failure count
rises while the Wi-Fi tasks are untouched.

Results go to `examples/multi_access_mec/output/`.

## Files

- `multi_access_mec.py` with `AccessAwareOrchestrator` and the single run
- `settings/` with `simulation_parameters.properties`, `applications.xml`, the
  three access device types in `edge_devices.xml`, `edge_datacenters.xml` and
  `cloud.xml`

## Where to go next

- [Fog layers](../fog_layers/README.md) for a placement that walks a fixed layer
  order instead of scoring each tier
- [Q-learning](../q_learning/README.md) for a tier choice learned from delay
  rather than estimated from the link

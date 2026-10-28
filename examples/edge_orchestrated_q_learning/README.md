# Edge-orchestrated Q-learning: the tier agent handed to an edge data center

## What it shows

The same learned tier policy as `examples/q_learning`, but the decision no longer
happens on the device. `enable_orchestrators` = true with `deploy_orchestrator` =
EDGE routes every request to the closest edge data center first, which adds a MAN
round trip before and after the placement. The agent itself is imported, not
copied: `QLearningOrchestrator` still scores states, picks a tier and updates the
table. Open `reward` and `results_returned`: the delay the agent is charged for
now contains that MAN hop, so the value it learns for a tier includes the cost of
delegating the choice, and a policy that looks good on-device can look worse here.
Read `initialize` and `node_in_tier` for the part that did not change.

```mermaid
sequenceDiagram
    participant dev as Device
    participant dc as Closest edge DC
    participant ag as QLearningOrchestrator
    dev->>dc: request, MAN hop
    dc->>ag: state = type, len bucket, load bucket
    ag->>ag: epsilon-greedy, eps 0.1
    ag->>dev: chosen tier, cloud edge or mist
    dev->>dc: result, MAN hop
    dc->>ag: reward = -(delay with MAN), or -1000
    ag->>ag: Q += 0.2 (r + 0.9 maxQ - Q)
```

## The scenario

`settings/` is the neighbourhood-scale version of the Q-learning example:

- 500 devices on a 2000 by 2000 meters map, with a 20 meters device-to-device
  range;
- the `ALL` architecture and the `Q_LEARNING` algorithm, `random_seed` = 7, ten
  simulated minutes, `enable_orchestrators` = true and `deploy_orchestrator` =
  EDGE, so the orchestrator runs on the edge tier;
- four linked edge data centers of 10 cores at 40000 MIPS and a cloud of 200
  cores;
- five device types (phones, tablets, laptops and two non-computing sensors) and
  the same three applications.

## Run it

From the repository root, after `pip install -e .`:

```bash
python examples/edge_orchestrated_q_learning/edge_orchestrated_q_learning.py
```

No-install variant:

```bash
PYTHONPATH=src python examples/edge_orchestrated_q_learning/edge_orchestrated_q_learning.py
```

## What to look for

```text
edge orchestrated        tasks= 56550 ok= 40930 avg_delay=0.1649   cloud=14674 edge=38713 mist= 3163 failed(delay)=15620 failed(mobility)=   0 energy=205.2936
```

- 38713 of 56550 tasks, roughly 68 percent, run at the edge, 14674 (about 26
  percent) go to the cloud and only 3163 stay in the mist, so 15620 tasks fail on
  delay and 40930 succeed. Delegation did not stop the learner from wasting work on
  the cloud, it just moved the rest of the load onto the data centers: the edge
  successes are 37485 of 38713 (96.8%) and the mist 2905 of 3163 (91.8%), while the
  cloud brings only 540 of 14674 (3.7%), which is 14134 of the 15620 delay
  failures. The CSV shows why: of the 13156.58 s of network time in this run,
  12516.25 s are spent on the single shared WAN link against 480.96 s on the LAN,
  so a task that leaves the neighbourhood queues behind every other task that does.
- The average completed delay, 0.1649 s, is the lowest of the family (the on-device
  run reaches 0.1742 s, the mist-only run 0.2539 s), and that is the honest read:
  it is low because the latency bound filtered out everything slow, leaving only
  quick successes in the average, not because the policy got better. The success
  rate (40930 over 56550, about 72 percent) now sits close to the on-device
  Q-learning run, where 4128 of 5550 tasks succeed (about 74 percent), so
  delegating the decision costs a little throughput and buys a shorter delay.
- Energy is 205.29 Wh for ten simulated minutes across 500 devices, the largest
  number in the family. The per-tier split says where it goes: mist 121.09 Wh,
  edge 79.53 Wh and cloud 4.68 Wh, so the bill is the fleet plus the four data
  centers running, and inside it the access links account for 49.13 Wh of Wi-Fi
  against 0.21 Wh on the WAN, far less than a cloud-heavy placement suggests.
- Results go to `examples/edge_orchestrated_q_learning/output/`, where the CSV
  holds this full scenario as a single row, so every number above is readable
  from it.

Set `enable_orchestrators` = false in `settings/` to run the agent back on the
device and watch the cloud share fall.

## Files

- `edge_orchestrated_q_learning.py`, a thin wrapper around the shared agent
- `../q_learning/q_learning.py` for `QLearningOrchestrator` itself
- `settings/` with `simulation_parameters.properties`, `applications.xml`,
  `edge_devices.xml`, `edge_datacenters.xml` and `cloud.xml`

## Where to go next

- [Q-learning](../q_learning/README.md) for the on-device version of this exact
  agent
- [Custom orchestrator](../custom_orchestrator/README.md) for a hand-written
  placement rule to compare the learned one against
- [Custom policies](../../README.md#custom-policies) in the main README

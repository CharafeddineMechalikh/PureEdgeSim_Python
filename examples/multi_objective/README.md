# Multi-objective RL: two value tables, one weighted decision

## What it shows

Delay and energy are different currencies, so learning them together in one table
blurs them. `MultiObjectiveOrchestrator` keeps two tables, `delay_values` and
`energy_values`, indexed by the same state (the application type and a task-length
bucket, `state_key` = `type|bucket` with buckets at 1000, 5000 and 20000 MI) and
by one action per tier the architecture allows. Each table is updated with the
textbook rule `Q += 0.2 * (reward + 0.9 * max Q(next) - Q)` (`LEARNING_RATE` =
0.2, `DISCOUNT_RATE` = 0.9, `EPSILON` = 0.1). The delay reward is
`-total_delay / max_latency` and the energy reward is the negative estimated
energy divided by `REFERENCE_ENERGY_WH` = 0.01, so 0.01 Wh maps to a reward of -1;
a failed task applies `-FAILURE_PENALTY` = -200 to both tables. Keeping the
objectives in separate tables means the trade-off is a decision-time parameter,
not a retraining: `find_computing_node` scores each action as
`DELAY_WEIGHT * delay_value + ENERGY_WEIGHT * energy_value`, both set to 1.0 here.

```mermaid
flowchart TD
    task["Task"] --> state["state_key: type|length bucket"]
    state --> eps{"random < 0.1?"}
    eps -->|yes| explore["Random feasible tier"]
    eps -->|no| score["score = 1.0*D + 1.0*E"]
    score --> dtab["delay_values"]
    score --> etab["energy_values"]
    explore --> run["Run on chosen tier"]
    score --> run
    run --> res{"task SUCCESS?"}
    res -->|yes| dr["d_r = -delay/latency<br/>e_r = -energy/0.01"]
    res -->|no| pen["both rewards = -200"]
    dr --> upd["Q += 0.2 (r + 0.9 maxQ - Q)"]
    pen --> upd
    upd --> state
    classDef tables fill:#cfe8ff,stroke:#333;
    class dtab,etab tables;
```

## The scenario

`settings/` runs one scenario, once, on a fixed seed, on the same topology as the
ant colony and priority examples:

- 300 devices on a 2000 by 2000 meters map, `ALL` architecture and the
  `SCALARIZED_Q` algorithm, `random_seed` = 53, five simulated minutes, decisions
  made on the device (`enable_orchestrators` = false);
- a fleet of five device types, two of which are sensors with no computing power;
- four edge data centers of 10 cores at 40000 MIPS, a cloud of 200 cores, and the
  shared 20 Mbps WAN at 0.06 s latency;
- the same three applications: Health (Hard Real-time, 500 MI, 0.02 s), Augmented
  reality (Soft Real-time, 5000 MI, 0.5 s) and HEAVY_COMP_APP (Non Real-time,
  30000 MI, 300 s).

## Run it

From the repository root, after `pip install -e .`:

```bash
python examples/multi_objective/multi_objective.py
```

No-install variant:

```bash
PYTHONPATH=src python examples/multi_objective/multi_objective.py
```

## What to look for

```text
SCALARIZED_Q  devices= 300 tasks= 16870 ok= 4017 avg_delay=0.1835 cloud=7637 edge=5519 mist=3714 energy=78.7241
```

- The energy table is what makes this run interesting, and it bites back. The
  cloud has 200 cores, so its estimated compute time, and therefore its estimated
  energy, is the smallest of the three tiers; with `ENERGY_WEIGHT` = 1.0 pulling
  as hard as the delay term, the agent ships 7637 tasks to the cloud, second only
  to the softmax run (7718) among the policies measured on this scenario, and far
  above the priority rule (5891) and the ant colony (4098).
- Only 375 of those 7637 cloud tasks succeed (4.9%). The reason is congestion:
  the shared WAN logged 127223 s of usage on this run, several times the 36648 s
  of the ant colony run, because every cloud placement pays a WAN transfer on the
  20 Mbps uplink. The delay table alone would have kept the tasks near the edge,
  but the equal weights let the energy table overrule it.
- The promised energy saving does not show up. Despite being the "energy-aware"
  policy, total energy is 78.72 Wh, above the ant colony (78.27) and the priority
  rule (76.52) on the same scenario and only just below the softmax run (79.46),
  because a task that fails after a long WAN transfer has already spent that
  energy for nothing. The per-tier split still favors mist for wins: 2637 of 3714
  mist tasks succeed (71%).
- Average delay, 0.1835 s, is a hair worse than the ant colony's 0.1776, and the
  success count, 4017, is between the ant colony (3855) and priority (4770).
  Results go to `examples/multi_objective/output/`.

This is a policy to tune rather than trust at the default weights: set
`ENERGY_WEIGHT` to 0.1 (or drop `REFERENCE_ENERGY_WH`) to let the delay table
dominate and watch the cloud placements collapse.

## Files

- `multi_objective.py` with `MultiObjectiveOrchestrator`
- `settings/` with `simulation_parameters.properties`, `applications.xml`,
  `edge_devices.xml`, `edge_datacenters.xml` and `cloud.xml`

## Where to go next

- [Q-learning](../q_learning/README.md) for the single delay-only table this
  example doubles into two objectives
- [Ant colony](../ant_colony/README.md) for a sampled policy on the same scenario
- [Output and metrics](../../docs/output-and-metrics.md) for how energy and WAN
  usage are accounted per tier
- [Custom policies](../../README.md#custom-policies) in the main README

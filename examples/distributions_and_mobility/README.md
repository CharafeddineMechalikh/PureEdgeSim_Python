# Distributions and mobility

## What it shows

How to configure a scenario from Python instead of editing the settings files.
The settings folder describes constants: every task of an application has the
same length, the same sizes, and the same gap between requests, and the devices
stand still. This example loads those files, then replaces the constants by
probability distributions and lets the devices move.

The distributions live in the `pureedgesim` package and are also accepted inside
the XML files. The example uses them directly:

- `LogNormalDistribution` for the task length, with the same mean as the
  constant and a third of it as standard deviation;
- `WeibullDistribution` for the request size;
- `ExponentialDistribution` for the inter-arrival gaps, derived from the rate;
- `NormalDistribution(2.0, 0.5).bounded(0.0, 5.0)` for the speed, so a draw is
  never negative;
- the `gauss-markov` mobility model for every device type, with its `alpha`,
  `std`, and `speed_std` options.

## The scenario

Both runs use `examples/default_settings` with 20 devices, five simulated
minutes, the `ALL` architecture, and `random_seed=7`. The first run keeps the
file values; the second replaces them as described above. `Randomness.set_seed`
and `Randomness.begin_scenario` make the draws reproducible across the two runs.

The script also prints a few draws before running, so the shape of each
distribution is visible without reading the CSV: one gap from the heavy
application, and six lognormal task lengths.

## Run it

From the repository root, after `pip install -e .`:

```bash
python examples/distributions_and_mobility/distributions_and_mobility.py
```

## What to look for

```text
constants, static      tasks= 1035 ok=  775 delay=0.2024   failed(delay)= 260 failed(mobility)=   0 energy=11.6066
distributions, mobile  tasks= 1006 ok=  793 delay=0.2132   failed(delay)= 213 failed(mobility)=   0 energy=10.9223
```

- The task count changes: the exponential gaps produce a different number of
  requests in the same simulated time.
- Fewer tasks miss their deadline in the second run, even though the mean delay
  is higher, because the lognormal mix includes many short tasks.
- `failed(mobility)` stays at zero: moving devices leave and re-enter range, but
  they are not lost, so mobility changes the destination, not the outcome.
- Results go to `output/examples/`.

Replace the `gauss-markov` model by `manhattan`, `levy-walk`, or the other models
listed in the README to compare movement patterns under the same workload.

## Files

- `distributions_and_mobility.py` with the parameter overrides and both runs
- `../default_settings/` for the base scenario files

## Where to go next

- [Custom orchestrator](../custom_orchestrator/README.md) for a different kind
  of Python-side configuration, the placement policy
- The settings folder section of the [main README](../../README.md#settings-folder)
  for the distribution syntax inside the XML files

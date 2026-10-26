"""Partitioning algorithms used by the graph and genetic examples.

Two solvers for the same question: how to split the subtasks of a service graph
between the available nodes. Both read the graph from the applications file
before the simulation starts, so the plan is computed once per application.

    python examples/graph_partitioning/graph_partitioning.py
    python examples/genetic_partitioning/genetic_partitioning.py

`GraphPartitioner` works on the structure of the graph: it separates the weakly
connected components, assigns the heaviest steps first to the least loaded
partition, then exchanges pairs of steps (Kernighan-Lin style) while the exchange
removes more dependency edges than it adds. `GeneticPartitioner` searches the
node of every subtask, and its fitness estimates the makespan of the pipeline
plus the time spent transferring results between nodes.
"""
from __future__ import annotations

from dataclasses import dataclass
from random import Random

from pureedgesim.config import Application


@dataclass(frozen=True)
class Step:
    """One subtask of a service graph, with the means of its distributions."""

    name: str
    dependencies: tuple[str, ...]
    length: float
    result_size: float


class ServiceGraph:
    """The dependency graph of an application that declares subtasks."""

    def __init__(self, steps) -> None:
        self.steps = tuple(steps)
        self.index: dict[str, int] = {}
        for position, step in enumerate(self.steps):
            if step.name in self.index:
                raise ValueError(f"Duplicate subtask name {step.name!r}")
            self.index[step.name] = position
        for step in self.steps:
            for dependency in step.dependencies:
                if dependency not in self.index:
                    raise ValueError(f"Subtask {step.name!r} depends on unknown subtask {dependency!r}")

    @classmethod
    def of(cls, application: Application) -> "ServiceGraph":
        return cls(Step(subtask.name, subtask.dependencies, subtask.task_length.mean(),
                        subtask.results_size.mean()) for subtask in application.subtasks)

    def __len__(self) -> int:
        return len(self.steps)

    def topological_order(self) -> list[int]:
        self._check_acyclic()
        remaining = [len(step.dependencies) for step in self.steps]
        dependents: list[list[int]] = [[] for _ in self.steps]
        for position, step in enumerate(self.steps):
            for dependency in step.dependencies:
                dependents[self.index[dependency]].append(position)
        ready = [position for position, count in enumerate(remaining) if count == 0]
        order: list[int] = []
        while ready:
            position = ready.pop(0)
            order.append(position)
            for dependent in dependents[position]:
                remaining[dependent] -= 1
                if remaining[dependent] == 0:
                    ready.append(dependent)
        return order

    def components(self) -> list[list[int]]:
        neighbours: list[list[int]] = [[] for _ in self.steps]
        for position, step in enumerate(self.steps):
            for dependency in step.dependencies:
                parent = self.index[dependency]
                neighbours[position].append(parent)
                neighbours[parent].append(position)
        visited = [False] * len(self.steps)
        components: list[list[int]] = []
        for start in range(len(self.steps)):
            if visited[start]:
                continue
            visited[start] = True
            component, stack = [], [start]
            while stack:
                position = stack.pop()
                component.append(position)
                for neighbour in neighbours[position]:
                    if not visited[neighbour]:
                        visited[neighbour] = True
                        stack.append(neighbour)
            components.append(sorted(component))
        return components

    def _check_acyclic(self) -> None:
        remaining = [len(step.dependencies) for step in self.steps]
        dependents: list[list[int]] = [[] for _ in self.steps]
        for position, step in enumerate(self.steps):
            for dependency in step.dependencies:
                dependents[self.index[dependency]].append(position)
        ready = [position for position, count in enumerate(remaining) if count == 0]
        visited = 0
        while ready:
            position = ready.pop()
            visited += 1
            for dependent in dependents[position]:
                remaining[dependent] -= 1
                if remaining[dependent] == 0:
                    ready.append(dependent)
        if visited != len(self.steps):
            raise ValueError("The service graph contains a cycle")


@dataclass(frozen=True)
class Partition:
    component: int
    index: int
    members: tuple[str, ...]
    load: float

    def __str__(self) -> str:
        return f"P{self.component}.{self.index} {list(self.members)} ({round(self.load)} MI)"


@dataclass(frozen=True)
class PartitionPlan:
    partition_of: dict[str, int]
    partitions: tuple[Partition, ...]
    cut_edges: int
    cross_traffic: float

    def describe(self) -> str:
        lines = [f"{len(self.partitions)} partitions, cut {self.cut_edges} edges "
                 f"({round(self.cross_traffic)} bits per request)"]
        lines.extend(f"  {partition}" for partition in self.partitions)
        return "\n".join(lines)


class GraphPartitioner:
    """Balanced min-cut partitioning with connected components and pair swaps."""

    balance_tolerance = 1.5
    max_refinement_passes = 100

    def partition(self, graph: ServiceGraph, partition_count: int) -> PartitionPlan:
        if partition_count < 1:
            raise ValueError("A graph needs at least one partition")
        graph.topological_order()

        partition_of_step = [-1] * len(graph)
        partition_of: dict[str, int] = {}
        partitions: list[Partition] = []
        for component_index, members in enumerate(graph.components()):
            count = min(partition_count, len(members))
            local = self._initial_assignment(graph, members, count)
            self._refine(graph, members, local, count)
            loads = self._loads(graph, members, local, count)

            global_index = []
            for part in range(count):
                names = tuple(graph.steps[members[i]].name for i in range(len(members)) if local[i] == part)
                global_index.append(len(partitions))
                partitions.append(Partition(component_index, part, names, loads[part]))
            for i, step in enumerate(members):
                partition_of_step[step] = global_index[local[i]]
                partition_of[graph.steps[step].name] = global_index[local[i]]

        cut_edges, cross_traffic = 0, 0.0
        for step, current in enumerate(graph.steps):
            for dependency in current.dependencies:
                parent = graph.index[dependency]
                if partition_of_step[parent] != partition_of_step[step]:
                    cut_edges += 1
                    cross_traffic += graph.steps[parent].result_size
        return PartitionPlan(partition_of, tuple(partitions), cut_edges, cross_traffic)

    @staticmethod
    def _initial_assignment(graph: ServiceGraph, members: list[int], count: int) -> list[int]:
        heaviest_first = sorted(range(len(members)),
                                key=lambda i: (-graph.steps[members[i]].length, members[i]))
        loads = [0.0] * count
        assignment = [0] * len(members)
        for i in heaviest_first:
            lightest = min(range(count), key=lambda part: loads[part])
            assignment[i] = lightest
            loads[lightest] += graph.steps[members[i]].length
        return assignment

    def _refine(self, graph: ServiceGraph, members: list[int], local: list[int], count: int) -> None:
        if count < 2:
            return
        average = sum(graph.steps[step].length for step in members) / count
        allowed = average * self.balance_tolerance
        cut = self._cut(graph, members, local)
        for _ in range(self.max_refinement_passes):
            best_delta, best_left, best_right = 0, -1, -1
            for left in range(len(members)):
                for right in range(left + 1, len(members)):
                    if local[left] == local[right]:
                        continue
                    local[left], local[right] = local[right], local[left]
                    if max(self._loads(graph, members, local, count)) <= allowed + 1e-9:
                        delta = self._cut(graph, members, local) - cut
                        if delta < best_delta:
                            best_delta, best_left, best_right = delta, left, right
                    local[left], local[right] = local[right], local[left]
            if best_left < 0:
                return
            local[best_left], local[best_right] = local[best_right], local[best_left]
            cut += best_delta

    @staticmethod
    def _cut(graph: ServiceGraph, members: list[int], local: list[int]) -> int:
        partition_of_step = [-1] * len(graph)
        for i, step in enumerate(members):
            partition_of_step[step] = local[i]
        cut = 0
        for i, step in enumerate(members):
            for dependency in graph.steps[step].dependencies:
                if partition_of_step[graph.index[dependency]] != local[i]:
                    cut += 1
        return cut

    @staticmethod
    def _loads(graph: ServiceGraph, members: list[int], local: list[int], count: int) -> list[float]:
        loads = [0.0] * count
        for i, step in enumerate(members):
            loads[local[i]] += graph.steps[step].length
        return loads


@dataclass(frozen=True)
class Candidate:
    """One node the genetic algorithm can choose for a subtask."""

    id: int
    label: str
    mips: float
    bandwidth: float

    def __str__(self) -> str:
        return f"{self.label}#{self.id}"


@dataclass(frozen=True)
class GeneticPlan:
    node_of: dict[str, Candidate]
    fitness: float
    makespan: float
    transfers: float
    imbalance: float

    @property
    def placement(self) -> dict[str, str]:
        return {name: str(candidate) for name, candidate in self.node_of.items()}

    def describe(self) -> str:
        return (f"fitness {self.fitness:.4f} (makespan {self.makespan:.4f} s, "
                f"transfers {self.transfers:.4f} s, imbalance {self.imbalance:.4f})\n"
                f"  {self.placement}")


class GeneticPartitioner:
    """Searches the node of every subtask with a seeded genetic algorithm."""

    tournament_size = 3
    crossover_rate = 0.85
    mutation_rate = 0.1
    elitism = 2
    communication_weight = 0.1
    imbalance_weight = 0.5

    def __init__(self, seed: int, population_size: int = 40, generations: int = 60) -> None:
        if population_size < 2:
            raise ValueError("A population needs at least two chromosomes")
        if generations < 0:
            raise ValueError("The number of generations cannot be negative")
        self.seed = seed
        self.population_size = population_size
        self.generations = generations

    def partition(self, graph: ServiceGraph, candidates: list[Candidate]) -> GeneticPlan:
        if not candidates:
            raise ValueError("A placement needs at least one computing node")
        order = graph.topological_order()
        random = Random(self.seed)
        population = [self._evaluate([random.randrange(len(candidates)) for _ in graph.steps],
                                     graph, candidates, order)
                      for _ in range(self.population_size)]
        best = min(population, key=lambda chromosome: chromosome[0])
        for _ in range(self.generations):
            population.sort(key=lambda chromosome: chromosome[0])
            next_generation = population[:self.elitism]
            while len(next_generation) < self.population_size:
                first = self._tournament(population, random)
                second = self._tournament(population, random)
                child = self._crossover(first[1], second[1], random)
                self._mutate(child, len(candidates), random)
                next_generation.append(self._evaluate(child, graph, candidates, order))
            population = next_generation
            generation_best = min(population, key=lambda chromosome: chromosome[0])
            if generation_best[0] < best[0]:
                best = generation_best
        fitness, genes, makespan, transfers, imbalance = best
        node_of = {graph.steps[step].name: candidates[genes[step]] for step in range(len(graph))}
        return GeneticPlan(node_of, fitness, makespan, transfers, imbalance)

    def _tournament(self, population, random: Random):
        winner = population[random.randrange(len(population))]
        for _ in range(self.tournament_size - 1):
            challenger = population[random.randrange(len(population))]
            if challenger[0] < winner[0]:
                winner = challenger
        return winner

    def _crossover(self, first: list[int], second: list[int], random: Random) -> list[int]:
        if random.random() >= self.crossover_rate:
            return list(first)
        return [random.choice((a, b)) for a, b in zip(first, second)]

    def _mutate(self, genes: list[int], candidates: int, random: Random) -> None:
        rate = self.mutation_rate / len(genes)
        for gene in range(len(genes)):
            if random.random() < rate:
                genes[gene] = random.randrange(candidates)

    def _evaluate(self, genes: list[int], graph: ServiceGraph, candidates: list[Candidate], order):
        finish = [0.0] * len(graph)
        work = [0.0] * len(candidates)
        transfers = 0.0
        for step in order:
            current = graph.steps[step]
            node = candidates[genes[step]]
            start = 0.0
            for dependency in current.dependencies:
                parent = graph.index[dependency]
                transfer = 0.0
                if genes[parent] != genes[step]:
                    bandwidth = min(candidates[genes[parent]].bandwidth, node.bandwidth)
                    transfer = graph.steps[parent].result_size / bandwidth
                transfers += transfer
                start = max(start, finish[parent] + transfer)
            duration = current.length / node.mips
            finish[step] = start + duration
            work[genes[step]] += duration

        makespan = max(finish)
        used = [value for value in work if value > 0]
        average = sum(used) / len(used) if used else 0.0
        busiest = max(work)
        imbalance = (busiest - average) / average if average else 0.0
        fitness = (makespan + self.communication_weight * transfers
                   + self.imbalance_weight * (busiest - average))
        return fitness, genes, makespan, transfers, imbalance

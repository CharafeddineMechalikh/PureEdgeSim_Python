"""The two partitioning solvers used by the graph and genetic examples."""
from __future__ import annotations

import pytest

from pureedgesim.partitioning import Candidate, GeneticPartitioner, GraphPartitioner, ServiceGraph, Step


def chain(lengths=(100, 100, 100, 100), result_size=200):
    """s0 -> s1 -> s2 -> s3, one weakly connected component."""
    steps = []
    for index, length in enumerate(lengths):
        dependencies = () if index == 0 else (f"s{index - 1}",)
        steps.append(Step(f"s{index}", dependencies, length, result_size))
    return ServiceGraph(steps)


# ---------------------------------------------------------------------------
# Service graph
# ---------------------------------------------------------------------------


def test_a_graph_keeps_the_declared_steps_and_their_index():
    graph = chain()
    assert len(graph) == 4
    assert graph.index == {"s0": 0, "s1": 1, "s2": 2, "s3": 3}
    assert graph.topological_order() == [0, 1, 2, 3]


def test_duplicate_names_are_rejected():
    with pytest.raises(ValueError, match="Duplicate subtask name 's0'"):
        ServiceGraph([Step("s0", (), 100, 10), Step("s0", (), 100, 10)])


def test_a_dependency_on_an_unknown_step_is_rejected():
    with pytest.raises(ValueError, match="depends on unknown subtask 'ghost'"):
        ServiceGraph([Step("s0", ("ghost",), 100, 10)])


def test_a_cycle_is_rejected():
    ring = ServiceGraph([Step("a", ("c",), 100, 10), Step("b", ("a",), 100, 10),
                         Step("c", ("b",), 100, 10)])
    with pytest.raises(ValueError, match="cycle"):
        ring.topological_order()
    with pytest.raises(ValueError, match="cycle"):
        GraphPartitioner().partition(ring, 2)


def test_components_are_the_weakly_connected_parts():
    graph = ServiceGraph([Step("a0", (), 100, 10), Step("a1", ("a0",), 100, 10),
                          Step("b0", (), 100, 10)])
    assert graph.components() == [[0, 1], [2]]


# ---------------------------------------------------------------------------
# Graph partitioning
# ---------------------------------------------------------------------------


def test_a_chain_is_cut_into_two_balanced_halves():
    plan = GraphPartitioner().partition(chain(), 2)
    groups = {partition.members for partition in plan.partitions}
    assert groups == {("s0", "s1"), ("s2", "s3")}
    assert plan.cut_edges == 1
    assert plan.cross_traffic == 200


def test_disconnected_components_are_partitioned_independently():
    graph = ServiceGraph([Step("a0", (), 100, 200), Step("a1", ("a0",), 100, 200),
                          Step("b0", (), 100, 200), Step("b1", ("b0",), 100, 200)])
    plan = GraphPartitioner().partition(graph, 2)
    assert len(plan.partitions) == 4
    assert {partition.component for partition in plan.partitions} == {0, 1}
    # Two partitions per component, so each two-step component loses one edge.
    assert plan.cut_edges == 2
    assert plan.cross_traffic == 400


def test_every_subtask_is_assigned_to_exactly_one_partition():
    graph = chain()
    plan = GraphPartitioner().partition(graph, 2)
    assigned = [name for partition in plan.partitions for name in partition.members]
    assert sorted(assigned) == ["s0", "s1", "s2", "s3"]
    assert sorted(plan.partition_of) == ["s0", "s1", "s2", "s3"]


def test_more_partitions_than_steps_gives_one_partition_per_step():
    plan = GraphPartitioner().partition(chain(), 7)
    assert len(plan.partitions) == 4
    assert all(len(partition.members) == 1 for partition in plan.partitions)


def test_a_single_partition_keeps_the_whole_graph_together():
    plan = GraphPartitioner().partition(chain(), 1)
    assert len(plan.partitions) == 1
    assert plan.partitions[0].members == ("s0", "s1", "s2", "s3")
    assert plan.cut_edges == 0


def test_a_partition_count_below_one_is_rejected():
    with pytest.raises(ValueError, match="at least one partition"):
        GraphPartitioner().partition(chain(), 0)


# ---------------------------------------------------------------------------
# Genetic partitioning
# ---------------------------------------------------------------------------


def candidates():
    return [Candidate(1, "Fast", 10000, 1e9), Candidate(2, "Slow", 1000, 1e8)]


def test_the_same_seed_gives_the_same_plan():
    first = GeneticPartitioner(11, population_size=10, generations=15).partition(chain(), candidates())
    second = GeneticPartitioner(11, population_size=10, generations=15).partition(chain(), candidates())
    assert first.placement == second.placement
    assert first.fitness == second.fitness


def test_every_subtask_gets_a_node():
    plan = GeneticPartitioner(3).partition(chain(), candidates())
    assert sorted(plan.node_of) == ["s0", "s1", "s2", "s3"]
    assert all(candidate.id in (1, 2) for candidate in plan.node_of.values())


def test_more_generations_never_return_a_worse_plan():
    graph = chain(lengths=(500, 100, 50, 900))
    initial = GeneticPartitioner(5, population_size=10, generations=0).partition(graph, candidates())
    evolved = GeneticPartitioner(5, population_size=10, generations=40).partition(graph, candidates())
    assert evolved.fitness <= initial.fitness


def test_a_fast_node_wins_when_transfers_are_cheap():
    graph = chain(lengths=(500, 500, 500, 500), result_size=1)
    plan = GeneticPartitioner(2, population_size=10, generations=20).partition(graph, candidates())
    assert set(plan.placement.values()) == {"Fast#1"}


def test_the_estimate_is_positive_and_reports_its_parts():
    plan = GeneticPartitioner(4).partition(chain(), candidates())
    assert plan.fitness > 0
    assert plan.makespan > 0
    assert plan.transfers >= 0
    assert plan.imbalance >= 0


def test_an_empty_candidate_list_is_rejected():
    with pytest.raises(ValueError, match="at least one computing node"):
        GeneticPartitioner(4).partition(chain(), [])


def test_a_population_below_two_is_rejected():
    with pytest.raises(ValueError, match="at least two chromosomes"):
        GeneticPartitioner(4, population_size=1)


def test_a_negative_number_of_generations_is_rejected():
    with pytest.raises(ValueError, match="cannot be negative"):
        GeneticPartitioner(4, generations=-1)


def test_a_cyclic_graph_is_rejected():
    ring = ServiceGraph([Step("a", ("b",), 100, 10), Step("b", ("a",), 100, 10)])
    with pytest.raises(ValueError, match="cycle"):
        GeneticPartitioner(4).partition(ring, candidates())

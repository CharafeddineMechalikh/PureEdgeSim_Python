"""Distributions: sampling, moments, bounds, the factory and the XML reader."""
from __future__ import annotations

import math
import random
import statistics
import xml.etree.ElementTree as ElementTree

import pytest

from pureedgesim.distribution import (BernoulliDistribution, BetaDistribution, BinomialDistribution,
                                    CategoricalDistribution, ConstantDistribution,
                                    DistributionFactory, ErlangDistribution, ExponentialDistribution,
                                    GammaDistribution, GeometricDistribution, LogNormalDistribution,
                                    NormalDistribution, ParetoDistribution, PoissonDistribution,
                                    ScaledDistribution, TriangularDistribution, UniformDistribution,
                                    WeibullDistribution, distribution_from_element)
from pureedgesim.randomness import Randomness


def make_rng(seed=7):
    return random.Random(seed)


@pytest.fixture(autouse=True)
def fixed_stream():
    """Every statistical check in this module draws from the same reproducible stream."""
    Randomness.set_seed(20261025)
    Randomness.begin_scenario(0)


def samples(distribution, count=4000):
    return [distribution.sample() for _ in range(count)]


@pytest.mark.parametrize("distribution,expected", [
    (ConstantDistribution(5.0), 5.0),
    (UniformDistribution(2.0, 8.0), 5.0),
    (TriangularDistribution(0.0, 3.0, 10.0), (0.0 + 3.0 + 10.0) / 3),
    (NormalDistribution(4.0, 2.0), 4.0),
    (ExponentialDistribution(9.0), 9.0),
    (GammaDistribution(2.0, 3.0), 6.0),
    (ErlangDistribution(4.0, 2.0), 8.0),
    (BetaDistribution(2.0, 3.0), 0.4),
    (BernoulliDistribution(0.25), 0.25),
    (BinomialDistribution(10, 0.3), 3.0),
    (GeometricDistribution(0.5), 2.0),
    (PoissonDistribution(6.0), 6.0),
])
def test_declared_means(distribution, expected):
    assert distribution.mean() == pytest.approx(expected, rel=1e-9)


def test_lognormal_mean_matches_the_target():
    distribution = LogNormalDistribution(10.0, 4.0)
    assert distribution.mean() == pytest.approx(10.0, rel=1e-9)


def test_pareto_and_weibull_means():
    assert ParetoDistribution(2.0, 3.0).mean() == pytest.approx(3.0)
    assert WeibullDistribution(2.0, 5.0).mean() == pytest.approx(5.0 * math.gamma(1.5), rel=1e-9)


def test_categorical_mean_and_bounds():
    distribution = CategoricalDistribution([1.0, 2.0, 4.0], [1.0, 1.0, 2.0])
    assert distribution.mean() == pytest.approx(11 / 4)
    assert (distribution.min, distribution.max) == (1.0, 4.0)


def test_categorical_requires_matching_weights():
    with pytest.raises(ValueError, match="weights"):
        CategoricalDistribution([1.0, 2.0], [1.0])


def test_constant_never_varies():
    assert set(samples(ConstantDistribution(3.0), 50)) == {3.0}


def test_uniform_stays_inside_and_covers_the_range():
    distribution = UniformDistribution(-2.0, 6.0)
    drawn = samples(distribution)
    assert min(drawn) >= -2.0 and max(drawn) <= 6.0
    assert statistics.mean(drawn) == pytest.approx(2.0, abs=0.1)


def test_normal_is_centered_and_bounded_by_variance():
    distribution = NormalDistribution(50.0, 5.0)
    drawn = samples(distribution)
    assert statistics.mean(drawn) == pytest.approx(50.0, abs=0.3)
    assert statistics.pstdev(drawn) == pytest.approx(5.0, rel=0.05)


def test_exponential_is_memoryless_enough_to_be_right():
    distribution = ExponentialDistribution(4.0)
    drawn = samples(distribution)
    assert min(drawn) >= 0.0
    assert statistics.mean(drawn) == pytest.approx(4.0, abs=0.2)


def test_poisson_and_binomial_are_integer_valued():
    for distribution in (PoissonDistribution(8.0), BinomialDistribution(20, 0.4),
                         GeometricDistribution(0.3), BernoulliDistribution(0.6)):
        assert distribution.is_discrete
        for value in samples(distribution, 500):
            assert float(value).is_integer()
    assert max(samples(PoissonDistribution(8.0))) <= 30
    assert max(samples(BinomialDistribution(20, 0.4))) <= 20


def test_poisson_switches_to_the_normal_approximation():
    high = PoissonDistribution(120.0)
    drawn = samples(high)
    assert statistics.mean(drawn) == pytest.approx(120.0, abs=3.0)


def test_sample_int_floors_the_draw():
    distribution = UniformDistribution(2.0, 5.0)
    for _ in range(200):
        assert distribution.sample_int() in (2, 3, 4)


def test_erlang_is_a_gamma_with_integer_shape():
    erlang = ErlangDistribution(3.0, 2.0)
    assert isinstance(erlang, GammaDistribution)
    assert erlang.mean() == pytest.approx(6.0)


def test_beta_bounds_and_sampling():
    distribution = BetaDistribution(1.0, 1.0)
    drawn = samples(distribution, 500)
    assert all(0.0 <= value <= 1.0 for value in drawn)


def test_bounded_rejects_an_inverted_range():
    with pytest.raises(ValueError, match="max >= min"):
        UniformDistribution(0.0, 1.0).bounded(5.0, 2.0)


def test_bounded_clamps_after_a_hundred_attempts():
    distribution = NormalDistribution(1000.0, 1.0).bounded(0.0, 10.0)
    assert max(samples(distribution, 500)) <= 10.0
    assert distribution.mean() == 10.0


def test_scaled_multiplies_sample_mean_and_bounds():
    distribution = UniformDistribution(1.0, 3.0).scaled(8000)
    assert distribution.mean() == pytest.approx(16000.0)
    assert (distribution.min, distribution.max) == (8000.0, 24000.0)


def test_scaled_keeps_integers_only_when_the_factor_is_whole():
    integer_factor = ScaledDistribution(PoissonDistribution(3.0), 2.0)
    float_factor = ScaledDistribution(PoissonDistribution(3.0), 0.5)
    assert integer_factor.is_discrete
    assert not float_factor.is_discrete
    assert all(value.is_integer() for value in samples(integer_factor, 200))


def test_factory_is_case_insensitive_and_returns_named_classes():
    assert isinstance(DistributionFactory.create("NORMAL", {"mean": 1, "std": 1}), NormalDistribution)
    assert isinstance(DistributionFactory.create("Uniform", {"min": 0, "max": 1}), UniformDistribution)


def test_factory_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="unknown distribution"):
        DistributionFactory.create("cauchy", {})


def test_factory_reports_a_missing_option():
    with pytest.raises(ValueError, match="requires the \"mean\""):
        DistributionFactory.create("normal", {"std": 2})


def test_factory_reports_a_non_numeric_option():
    with pytest.raises(ValueError, match="must be a number"):
        DistributionFactory.create("normal", {"mean": "ten", "std": 2})


def test_factory_applies_min_and_max_attributes():
    distribution = DistributionFactory.create("normal", {"mean": 5, "std": 2, "min": 0, "max": 8})
    assert max(samples(distribution, 500)) <= 8.0
    assert min(samples(distribution, 500)) >= 0.0


def test_factory_leaves_uniform_unwrapped():
    distribution = DistributionFactory.create("uniform", {"min": 0, "max": 5, "min_": 0})
    assert isinstance(distribution, UniformDistribution)


def test_every_factory_name_builds_a_distribution():
    options = {
        "constant": {"value": 1}, "uniform": {"min": 0, "max": 1}, "triangular": {"min": 0, "mode": 1, "max": 2},
        "normal": {"mean": 0, "std": 1}, "lognormal": {"mean": 1, "std": 1}, "exponential": {"mean": 1},
        "erlang": {"shape": 2, "scale": 1}, "gamma": {"shape": 2, "scale": 1}, "weibull": {"shape": 2, "scale": 1},
        "pareto": {"scale": 1, "shape": 2}, "beta": {"alpha": 1, "beta": 1}, "bernoulli": {"probability": 0.5},
        "binomial": {"trials": 5, "probability": 0.5}, "geometric": {"probability": 0.5}, "poisson": {"mean": 5},
        "categorical": {"values": "1,2", "weights": "1,1"},
    }
    assert set(options) == set(DistributionFactory.NAMES)
    for name, arguments in options.items():
        distribution = DistributionFactory.create(name, arguments, make_rng())
        assert distribution.min <= distribution.sample() <= distribution.max or distribution.is_discrete


def test_element_with_a_bare_number_is_a_constant():
    distribution = distribution_from_element(ElementTree.fromstring("<rate>20</rate>"))
    assert isinstance(distribution, ConstantDistribution)
    assert distribution.sample() == 20.0


def test_element_with_attributes_uses_the_factory():
    element = ElementTree.fromstring('<latency distribution="lognormal" mean="25" std="10" min="1"/>')
    distribution = distribution_from_element(element)
    assert isinstance(distribution, ScaledDistribution) or distribution.min == 1.0
    assert distribution.mean() >= 1.0


def test_empty_element_is_rejected():
    with pytest.raises(ValueError, match="expected a number or a distribution"):
        distribution_from_element(ElementTree.fromstring("<rate>  </rate>"))


def test_non_numeric_element_is_rejected():
    with pytest.raises(ValueError, match="must hold a number"):
        distribution_from_element(ElementTree.fromstring("<rate>fast</rate>"))


def test_same_seed_replays_the_draws():
    Randomness.set_seed(5)
    first = [NormalDistribution(0, 1, Randomness.get_random()).sample() for _ in range(20)]
    Randomness.set_seed(5)
    second = [NormalDistribution(0, 1, Randomness.get_random()).sample() for _ in range(20)]
    assert first == second


def test_each_iteration_gets_its_own_stream():
    Randomness.set_seed(5)
    Randomness.begin_scenario(0)
    first = [Randomness.get_random().random() for _ in range(10)]
    Randomness.set_seed(5)
    Randomness.begin_scenario(1)
    second = [Randomness.get_random().random() for _ in range(10)]
    assert first != second


def test_unseeded_randomness_still_works():
    Randomness.reset()
    assert 0.0 <= Randomness.get_random().random() < 1.0

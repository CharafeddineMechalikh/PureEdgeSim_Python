"""Probability distributions, the Python counterpart of the distribution package."""
from __future__ import annotations

import math
import random as _random
from abc import ABC, abstractmethod
from typing import Mapping, Sequence

from .randomness import Randomness

__all__ = [
    "Distribution", "ConstantDistribution", "UniformDistribution", "TriangularDistribution",
    "NormalDistribution", "LogNormalDistribution", "ExponentialDistribution", "ErlangDistribution",
    "GammaDistribution", "WeibullDistribution", "ParetoDistribution", "BetaDistribution",
    "BernoulliDistribution", "BinomialDistribution", "GeometricDistribution", "PoissonDistribution",
    "CategoricalDistribution", "BoundedDistribution", "ScaledDistribution", "DistributionFactory",
    "distribution_from_element",
]


class Distribution(ABC):
    is_discrete = False

    def __init__(self, rng: _random.Random | None = None) -> None:
        self._rng = rng

    @property
    def random(self) -> _random.Random:
        # Resolved per draw, not at construction: distributions are parsed before
        # the runner picks a seed and a scenario salt, so binding the stream early
        # would leave them drawing from the pre-seed generator.
        return self._rng if self._rng is not None else Randomness.get_random()

    @abstractmethod
    def sample(self) -> float: ...

    @abstractmethod
    def mean(self) -> float: ...

    @property
    @abstractmethod
    def min(self) -> float: ...

    @property
    @abstractmethod
    def max(self) -> float: ...

    def sample_int(self) -> int:
        return math.floor(self.sample())

    def bounded(self, minimum: float, maximum: float) -> "Distribution":
        return BoundedDistribution(self, minimum, maximum)

    def scaled(self, factor: float) -> "Distribution":
        return ScaledDistribution(self, factor)


class ConstantDistribution(Distribution):
    def __init__(self, value: float, rng=None) -> None:
        super().__init__(rng)
        self.value = float(value)

    def sample(self) -> float:
        return self.value

    def mean(self) -> float:
        return self.value

    @property
    def min(self) -> float:
        return self.value

    @property
    def max(self) -> float:
        return self.value

    def __repr__(self) -> str:
        return f"constant({self.value})"


class UniformDistribution(Distribution):
    def __init__(self, minimum: float, maximum: float, rng=None) -> None:
        super().__init__(rng)
        if maximum < minimum:
            raise ValueError(f"uniform requires max >= min, found [{minimum}, {maximum}]")
        self._min, self._max = float(minimum), float(maximum)

    def sample(self) -> float:
        return self.random.uniform(self._min, self._max)

    def mean(self) -> float:
        return (self._min + self._max) / 2

    @property
    def min(self) -> float:
        return self._min

    @property
    def max(self) -> float:
        return self._max


class TriangularDistribution(Distribution):
    def __init__(self, minimum: float, mode: float, maximum: float, rng=None) -> None:
        super().__init__(rng)
        if not minimum <= mode <= maximum:
            raise ValueError(f"triangular requires min <= mode <= max, found {minimum}, {mode}, {maximum}")
        self._min, self.mode, self._max = float(minimum), float(mode), float(maximum)

    def sample(self) -> float:
        return self.random.triangular(self._min, self._max, self.mode)

    def mean(self) -> float:
        return (self._min + self.mode + self._max) / 3

    @property
    def min(self) -> float:
        return self._min

    @property
    def max(self) -> float:
        return self._max


class NormalDistribution(Distribution):
    def __init__(self, mean: float, std: float, rng=None) -> None:
        super().__init__(rng)
        if std < 0:
            raise ValueError(f"normal requires std >= 0, found {std}")
        self._mean, self.std = float(mean), float(std)

    def sample(self) -> float:
        return self.random.gauss(self._mean, self.std)

    def mean(self) -> float:
        return self._mean

    @property
    def min(self) -> float:
        return -math.inf

    @property
    def max(self) -> float:
        return math.inf


class LogNormalDistribution(Distribution):
    """Parameterised by the mean and standard deviation of the value, not of its logarithm."""

    def __init__(self, mean: float, std: float, rng=None) -> None:
        super().__init__(rng)
        if mean <= 0 or std < 0:
            raise ValueError(f"lognormal requires mean > 0 and std >= 0, found {mean}, {std}")
        self._mean, self.std = float(mean), float(std)
        variance = std * std
        self.sigma = math.sqrt(math.log1p(variance / (mean * mean)))
        self.mu = math.log(mean) - self.sigma * self.sigma / 2

    def sample(self) -> float:
        return self.random.lognormvariate(self.mu, self.sigma)

    def mean(self) -> float:
        return self._mean

    @property
    def min(self) -> float:
        return 0.0

    @property
    def max(self) -> float:
        return math.inf


class ExponentialDistribution(Distribution):
    def __init__(self, mean: float, rng=None) -> None:
        super().__init__(rng)
        if mean <= 0:
            raise ValueError(f"exponential requires mean > 0, found {mean}")
        self._mean = float(mean)

    def sample(self) -> float:
        return self.random.expovariate(1.0 / self._mean)

    def mean(self) -> float:
        return self._mean

    @property
    def min(self) -> float:
        return 0.0

    @property
    def max(self) -> float:
        return math.inf


class GammaDistribution(Distribution):
    def __init__(self, shape: float, scale: float, rng=None) -> None:
        super().__init__(rng)
        if shape <= 0 or scale <= 0:
            raise ValueError(f"gamma requires shape > 0 and scale > 0, found {shape}, {scale}")
        self.shape, self.scale = float(shape), float(scale)

    def sample(self) -> float:
        return self.random.gammavariate(self.shape, self.scale)

    def mean(self) -> float:
        return self.shape * self.scale

    @property
    def min(self) -> float:
        return 0.0

    @property
    def max(self) -> float:
        return math.inf


class ErlangDistribution(GammaDistribution):
    def __init__(self, shape: int, scale: float, rng=None) -> None:
        if int(shape) != shape or shape < 1:
            raise ValueError(f"erlang requires a whole shape >= 1, found {shape}")
        super().__init__(int(shape), scale, rng)


class WeibullDistribution(Distribution):
    def __init__(self, shape: float, scale: float, rng=None) -> None:
        super().__init__(rng)
        if shape <= 0 or scale <= 0:
            raise ValueError(f"weibull requires shape > 0 and scale > 0, found {shape}, {scale}")
        self.shape, self.scale = float(shape), float(scale)

    def sample(self) -> float:
        return self.random.weibullvariate(self.scale, self.shape)

    def mean(self) -> float:
        return self.scale * math.gamma(1 + 1 / self.shape)

    @property
    def min(self) -> float:
        return 0.0

    @property
    def max(self) -> float:
        return math.inf


class ParetoDistribution(Distribution):
    def __init__(self, scale: float, shape: float, rng=None) -> None:
        super().__init__(rng)
        if scale <= 0 or shape <= 0:
            raise ValueError(f"pareto requires scale > 0 and shape > 0, found {scale}, {shape}")
        self.scale, self.shape = float(scale), float(shape)

    def sample(self) -> float:
        return self.random.paretovariate(self.shape) * self.scale

    def mean(self) -> float:
        return math.inf if self.shape <= 1 else self.shape * self.scale / (self.shape - 1)

    @property
    def min(self) -> float:
        return self.scale

    @property
    def max(self) -> float:
        return math.inf


class BetaDistribution(Distribution):
    def __init__(self, alpha: float, beta: float, rng=None) -> None:
        super().__init__(rng)
        if alpha <= 0 or beta <= 0:
            raise ValueError(f"beta requires alpha > 0 and beta > 0, found {alpha}, {beta}")
        self.alpha, self.beta = float(alpha), float(beta)

    def sample(self) -> float:
        return self.random.betavariate(self.alpha, self.beta)

    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def min(self) -> float:
        return 0.0

    @property
    def max(self) -> float:
        return 1.0


class BernoulliDistribution(Distribution):
    is_discrete = True

    def __init__(self, probability: float, rng=None) -> None:
        super().__init__(rng)
        if not 0 <= probability <= 1:
            raise ValueError(f"bernoulli requires 0 <= probability <= 1, found {probability}")
        self.probability = float(probability)

    def sample(self) -> float:
        return 1.0 if self.random.random() < self.probability else 0.0

    def mean(self) -> float:
        return self.probability

    @property
    def min(self) -> float:
        return 0.0

    @property
    def max(self) -> float:
        return 1.0


class BinomialDistribution(Distribution):
    is_discrete = True

    def __init__(self, trials: int, probability: float, rng=None) -> None:
        super().__init__(rng)
        if trials < 0 or not 0 <= probability <= 1:
            raise ValueError(f"binomial requires trials >= 0 and 0 <= p <= 1, found {trials}, {probability}")
        self.trials, self.probability = int(trials), float(probability)

    def sample(self) -> float:
        return float(sum(1 for _ in range(self.trials) if self.random.random() < self.probability))

    def mean(self) -> float:
        return self.trials * self.probability

    @property
    def min(self) -> float:
        return 0.0

    @property
    def max(self) -> float:
        return float(self.trials)


class GeometricDistribution(Distribution):
    """Number of trials up to and including the first success, so the support starts at 1."""

    is_discrete = True

    def __init__(self, probability: float, rng=None) -> None:
        super().__init__(rng)
        if not 0 < probability <= 1:
            raise ValueError(f"geometric requires 0 < probability <= 1, found {probability}")
        self.probability = float(probability)

    def sample(self) -> float:
        return float(math.ceil(math.log1p(-self.random.random()) / math.log1p(-self.probability))) \
            if self.probability < 1 else 1.0

    def mean(self) -> float:
        return 1.0 / self.probability

    @property
    def min(self) -> float:
        return 1.0

    @property
    def max(self) -> float:
        return math.inf


class PoissonDistribution(Distribution):
    is_discrete = True

    def __init__(self, mean: float, rng=None) -> None:
        super().__init__(rng)
        if mean <= 0:
            raise ValueError(f"poisson requires mean > 0, found {mean}")
        self._mean = float(mean)

    def sample(self) -> float:
        if self._mean < 30:
            limit = math.exp(-self._mean)
            product = self.random.random()
            count = 0
            while product > limit:
                count += 1
                product *= self.random.random()
            return float(count)
        # Normal approximation with continuity correction keeps large means cheap.
        return float(max(0, round(self.random.gauss(self._mean, math.sqrt(self._mean)))))

    def mean(self) -> float:
        return self._mean

    @property
    def min(self) -> float:
        return 0.0

    @property
    def max(self) -> float:
        return math.inf


class CategoricalDistribution(Distribution):
    def __init__(self, values: Sequence[float], weights: Sequence[float] | None = None, rng=None) -> None:
        super().__init__(rng)
        if not values:
            raise ValueError("categorical requires at least one value")
        self.values = [float(v) for v in values]
        self.weights = [float(w) for w in weights] if weights is not None else [1.0] * len(self.values)
        if len(self.weights) != len(self.values) or any(w < 0 for w in self.weights) or sum(self.weights) <= 0:
            raise ValueError("categorical weights must be non negative, match the values, and not all be zero")
        self.is_discrete = all(v == math.floor(v) for v in self.values)

    def sample(self) -> float:
        return self.random.choices(self.values, weights=self.weights, k=1)[0]

    def mean(self) -> float:
        total = sum(self.weights)
        return sum(v * w for v, w in zip(self.values, self.weights)) / total

    @property
    def min(self) -> float:
        return min(self.values)

    @property
    def max(self) -> float:
        return max(self.values)


class BoundedDistribution(Distribution):
    """Rejection sampling inside [min, max], clamped after one hundred attempts."""

    def __init__(self, delegate: Distribution, minimum: float, maximum: float) -> None:
        super().__init__(delegate._rng)
        if maximum < minimum:
            raise ValueError(f"bounds require max >= min, found [{minimum}, {maximum}]")
        self.delegate, self._min, self._max = delegate, float(minimum), float(maximum)
        self.is_discrete = delegate.is_discrete

    def sample(self) -> float:
        for _ in range(100):
            value = self.delegate.sample()
            if self._min <= value <= self._max:
                return value
        return min(self._max, max(self._min, self.delegate.sample()))

    def mean(self) -> float:
        return min(self._max, max(self._min, self.delegate.mean()))

    @property
    def min(self) -> float:
        return self._min

    @property
    def max(self) -> float:
        return self._max


class ScaledDistribution(Distribution):
    def __init__(self, delegate: Distribution, factor: float) -> None:
        super().__init__(delegate._rng)
        self.delegate, self.factor = delegate, float(factor)
        self.is_discrete = delegate.is_discrete and self.factor == math.floor(self.factor)

    def sample(self) -> float:
        return self.delegate.sample() * self.factor

    def mean(self) -> float:
        return self.delegate.mean() * self.factor

    @property
    def min(self) -> float:
        return min(self.delegate.min * self.factor, self.delegate.max * self.factor)

    @property
    def max(self) -> float:
        return max(self.delegate.min * self.factor, self.delegate.max * self.factor)


def _number(options: Mapping[str, object], name: str, distribution: str) -> float:
    if name not in options or str(options[name]).strip() == "":
        raise ValueError(f'{distribution} requires the "{name}" option, found {dict(options)}')
    try:
        return float(str(options[name]).strip())
    except ValueError as error:
        raise ValueError(f'{distribution}: the "{name}" option must be a number, found "{options[name]}"') from error


def _optional(options: Mapping[str, object], name: str, default: float) -> float:
    return _number(options, name, "") if name in options and str(options[name]).strip() != "" else default


class DistributionFactory:
    NAMES = ("constant", "uniform", "triangular", "normal", "lognormal", "exponential", "erlang",
             "gamma", "weibull", "pareto", "beta", "bernoulli", "binomial", "geometric", "poisson",
             "categorical")

    @classmethod
    def create(cls, name: str, options: Mapping[str, object] | None = None,
               rng: _random.Random | None = None) -> Distribution:
        options = dict(options or {})
        key = name.strip().lower()
        if key not in cls.NAMES:
            raise ValueError(f'unknown distribution "{name}". Known names: {", ".join(cls.NAMES)}')
        if key == "categorical":
            values = [float(v) for v in str(options.get("values", "")).split(",") if v.strip() != ""]
            raw_weights = str(options.get("weights", "") or "")
            weights = [float(w) for w in raw_weights.split(",") if w.strip() != ""] or None
            distribution: Distribution = CategoricalDistribution(values, weights, rng)
        elif key == "constant":
            distribution = ConstantDistribution(_number(options, "value", key), rng)
        elif key == "uniform":
            distribution = UniformDistribution(_number(options, "min", key), _number(options, "max", key), rng)
        elif key == "triangular":
            distribution = TriangularDistribution(_number(options, "min", key), _number(options, "mode", key),
                                                  _number(options, "max", key), rng)
        elif key == "normal":
            distribution = NormalDistribution(_number(options, "mean", key), _number(options, "std", key), rng)
        elif key == "lognormal":
            distribution = LogNormalDistribution(_number(options, "mean", key), _number(options, "std", key), rng)
        elif key == "exponential":
            distribution = ExponentialDistribution(_number(options, "mean", key), rng)
        elif key == "erlang":
            distribution = ErlangDistribution(_number(options, "shape", key), _number(options, "scale", key), rng)
        elif key == "gamma":
            distribution = GammaDistribution(_number(options, "shape", key), _number(options, "scale", key), rng)
        elif key == "weibull":
            distribution = WeibullDistribution(_number(options, "shape", key), _number(options, "scale", key), rng)
        elif key == "pareto":
            distribution = ParetoDistribution(_number(options, "scale", key), _number(options, "shape", key), rng)
        elif key == "beta":
            distribution = BetaDistribution(_number(options, "alpha", key), _number(options, "beta", key), rng)
        elif key == "bernoulli":
            distribution = BernoulliDistribution(_number(options, "probability", key), rng)
        elif key == "binomial":
            distribution = BinomialDistribution(int(_number(options, "trials", key)),
                                                _number(options, "probability", key), rng)
        elif key == "geometric":
            distribution = GeometricDistribution(_number(options, "probability", key), rng)
        else:
            distribution = PoissonDistribution(_number(options, "mean", key), rng)
        if key in ("uniform", "triangular"):
            return distribution
        minimum = _optional(options, "min", -math.inf)
        maximum = _optional(options, "max", math.inf)
        if math.isinf(minimum) and math.isinf(maximum):
            return distribution
        return BoundedDistribution(distribution, minimum, maximum)


def distribution_from_element(element, rng: _random.Random | None = None) -> Distribution:
    """Reads a PureEdgeSim XML element: a bare number or a distribution with attributes."""
    options = dict(element.attrib)
    name = options.pop("distribution", None)
    if name is None:
        text = (element.text or "").strip()
        if text == "":
            raise ValueError(f"<{element.tag}> is empty, expected a number or a distribution")
        try:
            return ConstantDistribution(float(text), rng)
        except ValueError as error:
            raise ValueError(f'<{element.tag}> must hold a number, found "{text}"') from error
    return DistributionFactory.create(name, options, rng)

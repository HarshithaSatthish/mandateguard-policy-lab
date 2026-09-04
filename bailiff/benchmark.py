from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from statistics import mean, pstdev
from typing import Iterable, Mapping


class DatasetMutationDetected(RuntimeError):
    """Raised when a frozen benchmark dataset no longer matches its manifest."""


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    dataset_sha256: str
    case_count: int
    seeds: tuple[int, ...]
    generation_config_sha256: str
    status: str = "frozen"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def dataset_hash(dataset: object) -> str:
    return sha256(canonical_json(dataset)).hexdigest()


def freeze_dataset(*, dataset_id: str, dataset: object, seeds: Iterable[int], generation_config: object, minimum_seeds: int = 5) -> DatasetManifest:
    ordered_seeds = tuple(seeds)
    if len(ordered_seeds) < minimum_seeds:
        raise ValueError(f"The benchmark requires at least {minimum_seeds} seeds")
    return DatasetManifest(
        dataset_id=dataset_id,
        dataset_sha256=dataset_hash(dataset),
        case_count=len(dataset) if hasattr(dataset, "__len__") else 0,
        seeds=ordered_seeds,
        generation_config_sha256=dataset_hash(generation_config),
    )


def verify_dataset(*, dataset: object, manifest: DatasetManifest) -> None:
    actual = dataset_hash(dataset)
    if actual != manifest.dataset_sha256:
        raise DatasetMutationDetected(
            f"DATASET_MUTATION_DETECTED: expected {manifest.dataset_sha256}, got {actual}"
        )


def summarize_seed_results(results: Mapping[int, float]) -> dict[str, object]:
    if len(results) < 5:
        raise ValueError("The final benchmark requires at least five recorded seeds")
    values = list(results.values())
    minimum = min(values)
    maximum = max(values)
    return {
        "per_seed": {str(seed): value for seed, value in sorted(results.items())},
        "seed_count": len(values),
        "mean": mean(values),
        "std_dev": pstdev(values),
        "min": minimum,
        "max": maximum,
        "spread": maximum - minimum,
    }

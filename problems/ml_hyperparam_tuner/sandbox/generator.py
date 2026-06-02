"""Generate synthetic classification datasets for hyperparameter tuning."""

import random
from typing import Optional

import numpy as np
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split


def generate_cases(num_cases: int, seed: Optional[int] = None) -> list[dict]:
    rng = random.Random(seed)
    cases = []
    for case_index in range(num_cases):
        case_seed = rng.randint(0, 2**31 - 1)
        np_rng = np.random.RandomState(case_seed)

        n_features = rng.choice([5, 10, 15, 20])
        n_informative = max(2, n_features - rng.randint(0, 5))
        n_redundant = max(0, n_features - n_informative - rng.randint(0, 3))
        n_samples = rng.choice([300, 500, 800, 1000])
        n_classes = rng.choice([2, 3, 4])

        X, y = make_classification(
            n_samples=n_samples,
            n_features=n_features,
            n_informative=n_informative,
            n_redundant=n_redundant,
            n_classes=n_classes,
            n_clusters_per_class=1,
            flip_y=0.05,
            class_sep=rng.uniform(0.5, 1.5),
            random_state=case_seed,
        )

        X_train_val, X_test, y_train_val, y_test = train_test_split(
            X, y, test_size=0.2, random_state=case_seed
        )
        X_train, X_val, y_train, y_val = train_test_split(
            X_train_val, y_train_val, test_size=0.25, random_state=case_seed
        )

        cases.append({
            "case_index": case_index,
            "n_features": int(n_features),
            "n_samples": int(n_samples),
            "n_classes": int(n_classes),
            "X_train": X_train.tolist(),
            "y_train": y_train.tolist(),
            "X_val": X_val.tolist(),
            "y_val": y_val.tolist(),
            "X_test": X_test.tolist(),
            "y_test": y_test.tolist(),
        })
    return cases

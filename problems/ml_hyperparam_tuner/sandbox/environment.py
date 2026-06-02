"""Environment state machine and scoring for ML hyperparameter tuning."""

import json
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC


AVAILABLE_MODELS = {
    "LogisticRegression": {
        "class": LogisticRegression,
        "params": {
            "C": {"type": "float", "min": 0.01, "max": 10.0},
        },
        "fixed_params": {"max_iter": 500, "random_state": 42},
    },
    "RandomForest": {
        "class": RandomForestClassifier,
        "params": {
            "n_estimators": {"type": "int", "min": 10, "max": 200},
            "max_depth": {"type": "int", "min": 2, "max": 20, "nullable": True},
        },
        "fixed_params": {"random_state": 42},
    },
    "SVM": {
        "class": SVC,
        "params": {
            "C": {"type": "float", "min": 0.1, "max": 10.0},
            "kernel": {"type": "choice", "options": ["linear", "rbf"]},
        },
        "fixed_params": {"random_state": 42},
    },
}


def _validate_params(model_name: str, params: dict) -> dict:
    """Validate and sanitize user-provided hyperparameters."""
    if model_name not in AVAILABLE_MODELS:
        raise ValueError(f"Unknown model: {model_name}. Available: {list(AVAILABLE_MODELS.keys())}")

    meta = AVAILABLE_MODELS[model_name]
    validated = {}
    for key, spec in meta["params"].items():
        if key not in params:
            raise ValueError(f"Missing required param: {key}")
        val = params[key]
        if spec.get("nullable") and val is None:
            validated[key] = None
            continue
        ptype = spec["type"]
        if ptype == "float":
            try:
                fval = float(val)
            except Exception:
                raise ValueError(f"Param {key} must be a float, got {val!r}")
            if not (spec["min"] <= fval <= spec["max"]):
                raise ValueError(f"Param {key}={fval} out of range [{spec['min']}, {spec['max']}]")
            validated[key] = fval
        elif ptype == "int":
            try:
                ival = int(val)
            except Exception:
                raise ValueError(f"Param {key} must be an int, got {val!r}")
            if not (spec["min"] <= ival <= spec["max"]):
                raise ValueError(f"Param {key}={ival} out of range [{spec['min']}, {spec['max']}]")
            validated[key] = ival
        elif ptype == "choice":
            sval = str(val)
            if sval not in spec["options"]:
                raise ValueError(f"Param {key}={sval} not in {spec['options']}")
            validated[key] = sval
        else:
            raise ValueError(f"Unknown param type: {ptype}")
    return validated


class HyperparamTuningEnv:
    def __init__(self, case_data: dict, max_trials: int = 10):
        self.case_data = case_data
        self.max_trials = max_trials
        self.trials_used = 0
        self.best_val_score = 0.0
        self.best_config: dict | None = None
        self.done = False
        self.success = False
        self.error = None

        self.X_train = np.array(case_data["X_train"])
        self.y_train = np.array(case_data["y_train"])
        self.X_val = np.array(case_data["X_val"])
        self.y_val = np.array(case_data["y_val"])
        self.X_test = np.array(case_data["X_test"])
        self.y_test = np.array(case_data["y_test"])

    def apply_action(self, action_name: str, payload: dict) -> Any:
        if action_name == "get_problem_info":
            return self.get_problem_info()
        if action_name == "train":
            return self.train(
                payload.get("model_name", ""),
                payload.get("params", {}),
            )
        if action_name == "submit_answer":
            return self.submit_answer(payload.get("config", {}))
        self.error = f"unknown action: {action_name}"
        return self.error

    def get_problem_info(self) -> dict:
        return {
            "n_features": self.case_data["n_features"],
            "n_samples": self.case_data["n_samples"],
            "n_classes": self.case_data["n_classes"],
            "available_models": {
                name: {
                    k: {sk: sv for sk, sv in v.items() if sk != "class"}
                    for k, v in meta["params"].items()
                }
                for name, meta in AVAILABLE_MODELS.items()
            },
            "max_trials": self.max_trials,
        }

    def train(self, model_name: str, params: dict) -> dict:
        if self.trials_used >= self.max_trials:
            raise RuntimeError("No trials remaining")

        validated = _validate_params(model_name, params)
        meta = AVAILABLE_MODELS[model_name]
        cls = meta["class"]
        build_kwargs = {**meta.get("fixed_params", {}), **validated}
        # Remove None values (e.g. max_depth=None means unlimited)
        build_kwargs = {k: v for k, v in build_kwargs.items() if v is not None}

        try:
            model = cls(**build_kwargs)
            model.fit(self.X_train, self.y_train)
            val_acc = float(model.score(self.X_val, self.y_val))
        except Exception as exc:
            raise RuntimeError(f"Training failed: {exc}")

        self.trials_used += 1
        if val_acc > self.best_val_score:
            self.best_val_score = val_acc
            self.best_config = {"model_name": model_name, "params": validated}

        return {
            "trial": self.trials_used,
            "accuracy": round(val_acc, 4),
            "trials_remaining": self.max_trials - self.trials_used,
        }

    def submit_answer(self, config: dict) -> dict:
        if not config:
            config = self.best_config or {}

        if not config or "model_name" not in config:
            self.done = True
            self.error = "No configuration submitted"
            return {"test_accuracy": 0.0, "score": 0.0, "error": self.error}

        model_name = config["model_name"]
        params = config.get("params", {})
        try:
            validated = _validate_params(model_name, params)
            meta = AVAILABLE_MODELS[model_name]
            cls = meta["class"]
            build_kwargs = {**meta.get("fixed_params", {}), **validated}
            build_kwargs = {k: v for k, v in build_kwargs.items() if v is not None}
            model = cls(**build_kwargs)
            model.fit(self.X_train, self.y_train)
            test_acc = float(model.score(self.X_test, self.y_test))
        except Exception as exc:
            self.done = True
            self.error = f"Evaluation failed: {exc}"
            return {"test_accuracy": 0.0, "score": 0.0, "error": self.error}

        self.done = True

        # Scoring rubric (hard mode: >= 0.90 to pass)
        if test_acc >= 0.95:
            score = 100
            self.success = True
        elif test_acc >= 0.90:
            score = 80
            self.success = True
        elif test_acc >= 0.85:
            score = 50
        elif test_acc >= 0.80:
            score = 20
        else:
            score = 0

        self._last_score = score
        return {
            "test_accuracy": round(test_acc, 4),
            "score": score,
        }

    def compute_score(self) -> float:
        # Called by run.py to get final score
        if self.done:
            return float(getattr(self, "_last_score", 0))
        return 0

    def output_data(self) -> dict:
        return {
            "trials_used": self.trials_used,
            "best_val_score": round(self.best_val_score, 4),
            "best_config": self.best_config,
            "success": self.success,
            "error": self.error,
        }

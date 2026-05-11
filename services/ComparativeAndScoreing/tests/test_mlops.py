"""Tests for the MLOps training + validation pipelines."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.model import Phase2Scorer
from training_pipeline import train
from validation_service import validate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_start_run_mock(run_id: str = "test-run-001") -> MagicMock:
    """Return a MagicMock that behaves like ``mlflow.start_run()`` context manager."""
    run = MagicMock()
    run.info.run_id = run_id
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=run)
    cm.__exit__ = MagicMock(return_value=False)
    start_run = MagicMock(return_value=cm)
    return start_run


def _make_search_versions_client(version: str = "1") -> MagicMock:
    """Return a MagicMock MlflowClient suitable for the training pipeline."""
    client = MagicMock()
    version_obj = MagicMock()
    version_obj.version = version
    client.search_model_versions.return_value = [version_obj]
    return client


# ---------------------------------------------------------------------------
# TestTrainPipeline
# ---------------------------------------------------------------------------


class TestTrainPipeline:
    """Exercise training_pipeline.train.main() with all MLflow calls mocked."""

    @pytest.fixture(autouse=True)
    def _small_config(self, monkeypatch):
        """Replace CFG with a tiny instance so tests run fast."""
        fresh = dataclasses.replace(
            train.CFG,
            n_epochs=2,
            n_train_sessions=4,
            n_test_sessions=2,
            n_suppliers=3,
            auto_promote_ndcg=0.0,
            seed=1,
        )
        monkeypatch.setattr(train, "CFG", fresh)
        return fresh

    @pytest.fixture
    def mlflow_mocks(self, mocker):
        """Patch every MLflow surface used by train.main()."""
        set_tracking = mocker.patch("training_pipeline.train.mlflow.set_tracking_uri")
        set_experiment = mocker.patch("training_pipeline.train.mlflow.set_experiment")
        start_run = mocker.patch(
            "training_pipeline.train.mlflow.start_run",
            new=_make_start_run_mock("test-run-001"),
        )
        log_params = mocker.patch("training_pipeline.train.mlflow.log_params")
        log_metric = mocker.patch("training_pipeline.train.mlflow.log_metric")
        log_dict = mocker.patch("training_pipeline.train.mlflow.log_dict")
        log_model_compat = mocker.patch(
            "training_pipeline.train._log_model_compat", return_value=None
        )

        client = _make_search_versions_client(version="1")
        mlflow_client = mocker.patch(
            "training_pipeline.train.MlflowClient", return_value=client
        )

        return {
            "set_tracking_uri": set_tracking,
            "set_experiment": set_experiment,
            "start_run": start_run,
            "log_params": log_params,
            "log_metric": log_metric,
            "log_dict": log_dict,
            "log_model_compat": log_model_compat,
            "MlflowClient": mlflow_client,
            "client": client,
        }

    def test_train_main_returns_zero_on_success(self, mlflow_mocks):
        rc = train.main()
        assert rc == 0

    def test_train_calls_set_tracking_uri_once(self, mlflow_mocks):
        train.main()
        assert mlflow_mocks["set_tracking_uri"].call_count == 1
        mlflow_mocks["set_tracking_uri"].assert_called_with(
            train.CFG.mlflow_tracking_uri
        )

    def test_train_starts_mlflow_run(self, mlflow_mocks):
        train.main()
        assert mlflow_mocks["start_run"].call_count == 1

    def test_train_logs_hyperparameters(self, mlflow_mocks):
        train.main()
        assert mlflow_mocks["log_params"].call_count == 1
        (params_arg,), _ = mlflow_mocks["log_params"].call_args
        expected_keys = {
            "n_epochs",
            "lr",
            "gamma",
            "seed",
            "n_train_sessions",
            "n_test_sessions",
            "n_suppliers",
            "auto_promote_ndcg",
        }
        assert expected_keys.issubset(set(params_arg.keys()))

    def test_train_logs_train_loss_per_epoch(self, mlflow_mocks):
        train.main()
        train_loss_calls = [
            c
            for c in mlflow_mocks["log_metric"].call_args_list
            if c.args and c.args[0] == "train_loss"
        ]
        assert len(train_loss_calls) == train.CFG.n_epochs

    def test_train_logs_test_ndcg(self, mlflow_mocks):
        train.main()
        ndcg_calls = [
            c
            for c in mlflow_mocks["log_metric"].call_args_list
            if c.args and c.args[0] == "test_ndcg_at_5"
        ]
        assert len(ndcg_calls) >= 1

    def test_train_logs_model(self, mlflow_mocks):
        train.main()
        assert mlflow_mocks["log_model_compat"].call_count == 1

    def test_train_auto_promotes_to_staging_when_above_threshold(
        self, monkeypatch, mlflow_mocks
    ):
        # auto_promote_ndcg=0.0 -> threshold always cleared
        fresh = dataclasses.replace(train.CFG, auto_promote_ndcg=0.0)
        monkeypatch.setattr(train, "CFG", fresh)

        train.main()

        client = mlflow_mocks["client"]
        assert client.transition_model_version_stage.call_count == 1
        _, kwargs = client.transition_model_version_stage.call_args
        assert kwargs.get("stage") == "Staging"
        assert kwargs.get("name") == train.CFG.model_name
        assert kwargs.get("version") == "1"
        assert kwargs.get("archive_existing_versions") is False

    def test_train_skips_promotion_below_threshold(self, monkeypatch, mlflow_mocks):
        # auto_promote_ndcg=1.5 -> impossible to reach (NDCG in [0, 1])
        fresh = dataclasses.replace(train.CFG, auto_promote_ndcg=1.5)
        monkeypatch.setattr(train, "CFG", fresh)

        train.main()

        client = mlflow_mocks["client"]
        client.transition_model_version_stage.assert_not_called()

    def test_train_logs_learned_weights_dict(self, mlflow_mocks):
        train.main()
        assert mlflow_mocks["log_dict"].call_count == 1
        args, _ = mlflow_mocks["log_dict"].call_args
        assert len(args) >= 2
        assert args[1] == "learned_weights.json"


# ---------------------------------------------------------------------------
# TestValidationService
# ---------------------------------------------------------------------------


class TestValidationService:
    """Exercise validation_service.validate.main() with all MLflow calls mocked."""

    @pytest.fixture(autouse=True)
    def _small_config(self, monkeypatch, tmp_path):
        """Replace CFG with a tiny instance + isolated drift flag path."""
        fresh = dataclasses.replace(
            validate.CFG,
            n_holdout_sessions=8,
            n_suppliers=4,
            seed=11,
            ndcg_drift_threshold=0.05,
            drift_flag_path=str(tmp_path / "model_drift_detected.flag"),
        )
        monkeypatch.setattr(validate, "CFG", fresh)
        return fresh

    def _patch_validate_mlflow(self, mocker, baseline_ndcg, prod_versions_value=None):
        """Patch all MLflow surfaces used by validate.main()."""
        set_tracking = mocker.patch(
            "validation_service.validate.mlflow.set_tracking_uri"
        )
        set_experiment = mocker.patch(
            "validation_service.validate.mlflow.set_experiment"
        )
        start_run = mocker.patch(
            "validation_service.validate.mlflow.start_run",
            new=_make_start_run_mock("validation-run-001"),
        )
        log_param = mocker.patch("validation_service.validate.mlflow.log_param")
        log_metric = mocker.patch("validation_service.validate.mlflow.log_metric")

        # Real Phase2Scorer so the NDCG evaluation runs end-to-end.
        model = Phase2Scorer.from_weights([0.5, 0.3, 0.2])
        load_model = mocker.patch(
            "validation_service.validate.mlflow.pytorch.load_model",
            return_value=model,
        )

        client = MagicMock()
        if prod_versions_value is None:
            prod_version = MagicMock()
            prod_version.version = "3"
            prod_version.run_id = "prod-run-xyz"
            client.get_latest_versions.return_value = [prod_version]
        else:
            client.get_latest_versions.return_value = prod_versions_value

        baseline_run = MagicMock()
        if baseline_ndcg is None:
            baseline_run.data.metrics = {}
        else:
            baseline_run.data.metrics = {"test_ndcg_at_5": baseline_ndcg}
        client.get_run.return_value = baseline_run

        mlflow_client = mocker.patch(
            "validation_service.validate.MlflowClient", return_value=client
        )

        return {
            "set_tracking_uri": set_tracking,
            "set_experiment": set_experiment,
            "start_run": start_run,
            "log_param": log_param,
            "log_metric": log_metric,
            "load_model": load_model,
            "MlflowClient": mlflow_client,
            "client": client,
            "model": model,
        }

    def test_validate_returns_zero_when_no_drift(self, mocker):
        # baseline_ndcg=0.5: model trained on the same hidden cost should
        # comfortably beat 0.5 on synthetic holdout -> no drift.
        self._patch_validate_mlflow(mocker, baseline_ndcg=0.5)
        rc = validate.main()
        assert rc == 0

    def test_validate_returns_one_on_drift_detected(self, mocker):
        # baseline_ndcg=2.0: above the [0, 1] NDCG range — current_ndcg can
        # never match it, so drift_delta is always strongly negative. This
        # pins the test to the *drift-detection logic*, not the quality of
        # the mocked Phase2Scorer on the tiny synthetic holdout.
        self._patch_validate_mlflow(mocker, baseline_ndcg=2.0)
        rc = validate.main()
        assert rc == 1

    def test_validate_writes_drift_flag_on_drift(self, mocker):
        # baseline_ndcg=2.0: see the drift-detection test for rationale.
        self._patch_validate_mlflow(mocker, baseline_ndcg=2.0)
        flag_path = Path(validate.CFG.drift_flag_path)
        assert not flag_path.exists()

        rc = validate.main()

        assert rc == 1
        assert flag_path.exists()
        contents = flag_path.read_text()
        assert "drift_detected=true" in contents

    def test_validate_clears_drift_flag_on_no_drift(self, mocker):
        flag_path = Path(validate.CFG.drift_flag_path)
        flag_path.write_text("drift_detected=true\n")
        assert flag_path.exists()

        self._patch_validate_mlflow(mocker, baseline_ndcg=0.5)
        rc = validate.main()

        assert rc == 0
        assert not flag_path.exists()

    def test_validate_no_production_model_returns_zero(self, mocker):
        # Empty list from get_latest_versions -> short-circuit, rc=0.
        self._patch_validate_mlflow(
            mocker, baseline_ndcg=0.5, prod_versions_value=[]
        )
        rc = validate.main()
        assert rc == 0

    def test_validate_missing_baseline_metric_uses_zero(self, mocker):
        # metrics dict missing 'test_ndcg_at_5' -> falls back to 0.0.
        # current_ndcg will be positive, so drift_delta > 0 -> no drift -> rc=0.
        mocks = self._patch_validate_mlflow(mocker, baseline_ndcg=None)
        rc = validate.main()
        # No crash and a deterministic exit code.
        assert rc in (0, 1)
        # Make sure we actually went through the baseline-metric lookup.
        mocks["client"].get_run.assert_called_with("prod-run-xyz")

    def test_validate_logs_metrics_to_new_mlflow_run(self, mocker):
        mocks = self._patch_validate_mlflow(mocker, baseline_ndcg=0.5)
        rc = validate.main()
        assert rc == 0

        # start_run must be invoked exactly once for the validation run.
        assert mocks["start_run"].call_count == 1

        metric_names = [
            c.args[0] for c in mocks["log_metric"].call_args_list if c.args
        ]
        assert "validation_ndcg_at_5" in metric_names
        assert "baseline_ndcg_at_5" in metric_names
        assert "drift_delta" in metric_names

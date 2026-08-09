"""Concrete numerical adapter for research-only R3 nested temporal CV."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from decimal import Decimal
from importlib.metadata import version as package_version

import numpy as np
import statsmodels.api as sm  # type: ignore[import-untyped]
from numpy.typing import NDArray
from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]
from sklearn.linear_model import Lasso  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from apps.macro_factor.domain._runner_support import hash_payload
from apps.macro_factor.domain.entities import (
    EvaluationMetrics,
    ExternalLassoSelectionEvidence,
    ExternalMacroFactorResearchResult,
    FactorLifecycleStatus,
    FactorWeight,
    FactorWeightVersion,
    ModelEvaluationEvidence,
    RetirementPolicy,
    SampleSegment,
    calculate_factor_weight_hash,
)
from apps.macro_factor.domain.reproducible_runner import (
    ExecutionFoldBinding,
    ExternalAlphaScore,
    ExternalConcreteFitEvidence,
    ExternalDatedFactorOutput,
    ExternalFeatureStandardization,
    ExternalFoldPrediction,
    ExternalInnerFoldScore,
    ExternalNestedCVArtifact,
    ExternalOLSCoefficientDiagnostic,
    ExternalOuterFoldSelectionEvidence,
    ExternalProxyCoefficient,
    MacroFactorRunnerSpec,
    NestedCVExecutionRequest,
    OptimizationDirection,
    PITResearchDataset,
    PITResearchRow,
    ResearchOutputValidityPolicy,
    VersionedResearchContract,
)

FloatArray = NDArray[np.float64]
IMPLEMENTATION_ID = "agom.macro-factor.sklearn-nested-cv-lasso.v1"


def _decimal(value: float | int | np.float64 | np.int64) -> Decimal:
    numeric = float(value)
    if not np.isfinite(numeric):
        raise ValueError("numerical evidence must be finite")
    result = Decimal(format(numeric, ".15g"))
    return Decimal("0") if result == 0 else result


@dataclass(frozen=True)
class SklearnNestedCVFittingConfig:
    """Explicit governed configuration for the concrete numerical boundary."""

    selection_protocol: VersionedResearchContract
    metrics_protocol: VersionedResearchContract
    parameter_contract: VersionedResearchContract
    benchmark_contract: VersionedResearchContract
    cost_model_contract: VersionedResearchContract
    retirement_policy: RetirementPolicy
    transaction_cost_rate: Decimal
    max_iterations: int
    tolerance: Decimal
    zero_tolerance: Decimal
    economic_interpretation: str

    def __post_init__(self) -> None:
        if not self.economic_interpretation.strip():
            raise ValueError("economic_interpretation cannot be blank")
        for decimal_value, label in (
            (self.transaction_cost_rate, "transaction_cost_rate"),
            (self.tolerance, "tolerance"),
            (self.zero_tolerance, "zero_tolerance"),
        ):
            if not decimal_value.is_finite() or decimal_value < 0:
                raise ValueError(f"{label} must be a finite non-negative Decimal")
        if self.tolerance == 0 or self.zero_tolerance == 0:
            raise ValueError("numerical tolerances must be positive")
        if isinstance(self.max_iterations, bool) or self.max_iterations <= 0:
            raise ValueError("max_iterations must be positive")


@dataclass(frozen=True)
class _ModelFit:
    scaler: StandardScaler
    model: Lasso
    coefficients: FloatArray
    weights: FloatArray
    selected_indices: tuple[int, ...]


@dataclass(frozen=True)
class _FoldCalculation:
    selection: ExternalOuterFoldSelectionEvidence
    final_fit: _ModelFit
    oos_predictions: tuple[ExternalFoldPrediction, ...]
    train_actual: FloatArray
    train_predicted: FloatArray
    validation_actual: FloatArray
    validation_predicted: FloatArray
    oos_actual: FloatArray
    oos_predicted: FloatArray


class SklearnNestedCVLassoRunner:
    """Fit concrete Lasso models strictly inside preregistered temporal folds."""

    def __init__(self, config: SklearnNestedCVFittingConfig) -> None:
        self._config = config
        self._sklearn_version = package_version("scikit-learn")
        self._numpy_version = package_version("numpy")
        self._statsmodels_version = package_version("statsmodels")
        self._producer_ref = (
            f"{IMPLEMENTATION_ID};numpy={self._numpy_version};"
            f"scikit-learn={self._sklearn_version};"
            f"statsmodels={self._statsmodels_version}"
        )
        self._estimator_version = f"scikit-learn/{self._sklearn_version}:Lasso"
        self._standardization_version = f"scikit-learn/{self._sklearn_version}:StandardScaler"

    def execute(
        self,
        *,
        request: NestedCVExecutionRequest,
        dataset: PITResearchDataset,
        spec: MacroFactorRunnerSpec,
    ) -> ExternalNestedCVArtifact | None:
        """Return canonical research evidence, or ``None`` on any unsafe input."""

        try:
            return self._execute(request=request, dataset=dataset, spec=spec)
        except (ArithmeticError, TypeError, ValueError, np.linalg.LinAlgError):
            return None

    def _execute(
        self,
        *,
        request: NestedCVExecutionRequest,
        dataset: PITResearchDataset,
        spec: MacroFactorRunnerSpec,
    ) -> ExternalNestedCVArtifact:
        validity_policy = self._validate_bindings(
            request=request,
            dataset=dataset,
            spec=spec,
        )
        rows = dataset.rows_by_id
        self._validate_finite_dataset(dataset)
        calculations = tuple(
            self._calculate_fold(
                binding=binding,
                rows=rows,
                candidate_codes=request.candidate_asset_codes,
                request=request,
            )
            for binding in request.folds
        )
        final = next(
            item for item in calculations if item.selection.fold_id == request.final_fold_id
        )
        final_coefficients = final.selection.coefficients
        selected = tuple(item for item in final_coefficients if item.lasso_coefficient != 0)
        if not selected or final.selection.concrete_fit is None:
            raise ValueError("final Lasso fit selected no governed candidate")
        weights = tuple(
            FactorWeight(
                asset_code=item.asset_code,
                lasso_coefficient=item.lasso_coefficient,
                factor_weight=item.factor_weight,
            )
            for item in selected
        )
        weight_version = FactorWeightVersion(
            factor_version=spec.factor_version,
            calculated_at=spec.calculated_at,
            weights=weights,
            weight_hash=calculate_factor_weight_hash(
                factor_version=spec.factor_version,
                calculated_at=spec.calculated_at,
                weights=weights,
            ),
        )
        fold_selections = tuple(item.selection for item in calculations)
        coefficient_path_hash = hash_payload(
            [
                {
                    "fold_id": item.fold_id,
                    "coefficients": [value.canonical_payload() for value in item.coefficients],
                }
                for item in fold_selections
            ]
        )
        selection_report_hash = hash_payload([item.canonical_payload() for item in fold_selections])
        selection = ExternalLassoSelectionEvidence(
            evidence_id=hash_payload(
                {"request_hash": request.content_hash, "kind": "lasso-selection"}
            ),
            producer_ref=self._producer_ref,
            produced_at=spec.calculated_at,
            computation_origin="infrastructure_concrete_fit",
            estimator="lasso",
            validation_method="nested_cv",
            inner_fold_count=len(request.folds[0].inner_folds),
            outer_fold_count=len(request.folds),
            alpha_grid=request.alpha_grid,
            selected_alpha=final.selection.selected_alpha,
            optimization_metric=request.optimization_metric,
            coefficient_path_hash=coefficient_path_hash,
            selection_report_hash=selection_report_hash,
            selected_asset_codes=tuple(item.asset_code for item in selected),
        )
        stability, turnover = self._portfolio_diagnostics(fold_selections)
        cost = turnover * self._config.transaction_cost_rate
        evaluation = ModelEvaluationEvidence(
            in_sample=self._metrics(
                SampleSegment.IN_SAMPLE,
                calculations,
                "train_actual",
                "train_predicted",
                len(selected),
                stability,
                turnover,
                cost,
            ),
            validation=self._metrics(
                SampleSegment.VALIDATION,
                calculations,
                "validation_actual",
                "validation_predicted",
                len(selected),
                stability,
                turnover,
                cost,
            ),
            out_of_sample=self._metrics(
                SampleSegment.OUT_OF_SAMPLE,
                calculations,
                "oos_actual",
                "oos_predicted",
                len(selected),
                stability,
                turnover,
                cost,
            ),
            benchmark_version=self._config.benchmark_contract.version,
            cost_model_version=self._config.cost_model_contract.version,
            bic=final.selection.concrete_fit.ols_bic,
            statistical_significance_summary=self._significance_summary(
                final.selection.concrete_fit
            ),
            statistical_significance_evidence_ref=(
                f"ols-refit-sha256:{final.selection.concrete_fit.evidence_hash}"
            ),
            economic_interpretation=self._config.economic_interpretation,
            evidence_hash=hash_payload(
                {
                    "metrics_protocol": self._config.metrics_protocol.content_hash,
                    "benchmark": self._config.benchmark_contract.content_hash,
                    "cost_model": self._config.cost_model_contract.content_hash,
                    "output_validity_policy": validity_policy.content_hash,
                    "implementation": self._producer_ref,
                    "fit": final.selection.concrete_fit.evidence_hash,
                    "weight_hash": weight_version.weight_hash,
                    "stability": str(stability),
                    "turnover": str(turnover),
                    "cost": str(cost),
                }
            ),
        )
        result = ExternalMacroFactorResearchResult(
            result_id=hash_payload(
                {"request_hash": request.content_hash, "weight_hash": weight_version.weight_hash}
            ),
            factor_version=spec.factor_version,
            target=spec.target,
            candidates=spec.candidates,
            pit_manifest_id=request.pit_manifest_id,
            pit_manifest_hash=request.pit_manifest_hash,
            reproducibility=spec.reproducibility,
            split=spec.temporal_split,
            selection=selection,
            evaluation=evaluation,
            weights=weight_version,
            retirement_policy=self._config.retirement_policy,
            lifecycle_status=FactorLifecycleStatus.RESEARCH_ONLY,
            retirement_evidence=None,
        )
        predictions = tuple(
            prediction for item in calculations for prediction in item.oos_predictions
        )
        inference = dataset.inference_row
        if inference is None:
            raise ValueError("one label-free inference row is required")
        inference_features = np.asarray(
            [
                [
                    float(inference.proxy_value(asset_code))
                    for asset_code in request.candidate_asset_codes
                ]
            ],
            dtype=np.float64,
        )
        inference_value = _decimal(
            np.asarray(
                final.final_fit.model.predict(final.final_fit.scaler.transform(inference_features)),
                dtype=np.float64,
            )[0]
        )
        dated_output = ExternalDatedFactorOutput(
            output_role=spec.target.output_role,
            observation_date=inference.observation_date,
            target_period_start=inference.target_period.period_start,
            target_period_end=inference.target_period.period_end,
            horizon_periods=spec.target.horizon_periods,
            horizon_unit=spec.target.horizon_unit,
            knowledge_as_of=dataset.manifest_as_of,
            valid_until=validity_policy.valid_until(spec.calculated_at),
            value=inference_value,
            unit=spec.target.unit,
        )
        return ExternalNestedCVArtifact.create(
            evidence_id=hash_payload(
                {"request_hash": request.content_hash, "kind": "concrete-artifact"}
            ),
            producer_ref=self._producer_ref,
            produced_at=spec.calculated_at,
            request_hash=request.content_hash,
            result=result,
            fold_selections=fold_selections,
            predictions=predictions,
            dated_outputs=(dated_output,),
            validity_policy=validity_policy,
        )

    def _validate_bindings(
        self,
        *,
        request: NestedCVExecutionRequest,
        dataset: PITResearchDataset,
        spec: MacroFactorRunnerSpec,
    ) -> ResearchOutputValidityPolicy:
        validity_policy = spec.output_validity_policy.validated_copy()
        if any(not alpha.is_finite() or alpha <= 0 for alpha in request.alpha_grid):
            raise ValueError("alpha family must contain finite positive values")
        if request.alpha_grid != spec.plan.alpha_grid:
            raise ValueError("request alpha family drifted from preregistration")
        if request.dataset_hash != dataset.content_hash:
            raise ValueError("request does not bind the exact PIT dataset")
        if (
            request.pit_manifest_id != dataset.manifest_id
            or request.pit_manifest_hash.lower() != dataset.manifest_hash.lower()
            or request.pit_manifest_content_hash.lower() != dataset.manifest_content_hash.lower()
            or request.pit_manifest_content_hash.lower()
            != spec.expected_manifest_content_hash.lower()
        ):
            raise ValueError("request does not bind the exact PIT manifest projection")
        inference = dataset.inference_row
        if inference is None:
            raise ValueError("one label-free inference row is required")
        if (
            request.inference_row_id != inference.row_id
            or request.inference_row_hash != hash_payload(inference.canonical_payload())
            or request.inference_target_period_id != inference.target_period.period_id
            or request.inference_target_calendar_id != inference.target_period.calendar_id
            or request.inference_target_calendar_version != inference.target_period.calendar_version
            or request.inference_target_calendar_hash.lower()
            != inference.target_period.calendar_hash.lower()
            or request.inference_target_period_hash != inference.target_period.content_hash
        ):
            raise ValueError("request inference-row binding mismatch")
        if (
            request.target_code != spec.target.target_code
            or request.target_code != dataset.target_code
        ):
            raise ValueError("target binding mismatch")
        expected_candidates = tuple(item.asset_code for item in spec.candidates)
        if (
            request.candidate_asset_codes != expected_candidates
            or dataset.candidate_asset_codes != expected_candidates
        ):
            raise ValueError("candidate universe/order mismatch")
        exact_contracts = (
            (self._config.selection_protocol, spec.selection_protocol),
            (self._config.metrics_protocol, spec.metrics_protocol),
            (self._config.benchmark_contract, spec.historical_mean_benchmark),
            (self._config.cost_model_contract, spec.cost_model),
            (
                self._config.parameter_contract,
                VersionedResearchContract(
                    spec.reproducibility.parameter_version,
                    spec.reproducibility.parameter_hash,
                ),
            ),
        )
        if any(configured != governed for configured, governed in exact_contracts):
            raise ValueError("concrete runner contract identity mismatch")
        if (
            request.plan_hash != spec.plan.content_hash
            or request.plan_version != spec.plan.policy_version
        ):
            raise ValueError("request plan binding mismatch")
        if request.optimization_metric == "validation_mean_squared_error":
            expected_direction = OptimizationDirection.MINIMIZE
        elif request.optimization_metric == "validation_information_coefficient":
            expected_direction = OptimizationDirection.MAXIMIZE
        else:
            raise ValueError("unsupported preregistered optimization metric")
        if request.optimization_direction is not expected_direction:
            raise ValueError("optimization direction does not match metric")
        if (
            request.output_validity_policy_version != validity_policy.policy_version
            or request.output_validity_policy_hash != validity_policy.content_hash
            or request.output_valid_for_seconds != validity_policy.valid_for_seconds
            or request.output_maximum_valid_for_seconds != validity_policy.maximum_valid_for_seconds
        ):
            raise ValueError("request output-validity policy binding mismatch")
        freshness_policy = spec.input_knowledge_freshness_policy.validated_copy()
        manifest_fresh_until = freshness_policy.manifest_expires_at(dataset.manifest_as_of)
        inference_fresh_until = freshness_policy.inference_expires_at(inference.available_at)
        if (
            request.input_freshness_policy_version != freshness_policy.policy_version
            or request.input_freshness_policy_hash.lower() != freshness_policy.content_hash.lower()
            or request.max_manifest_age_seconds != freshness_policy.max_manifest_age_seconds
            or request.max_inference_age_seconds != freshness_policy.max_inference_age_seconds
            or request.maximum_allowed_input_age_seconds
            != freshness_policy.maximum_allowed_age_seconds
            or request.manifest_fresh_until != manifest_fresh_until
            or request.inference_fresh_until != inference_fresh_until
        ):
            raise ValueError("request input-freshness policy binding mismatch")
        output_valid_until = validity_policy.valid_until(spec.calculated_at)
        if (
            spec.calculated_at > manifest_fresh_until
            or spec.calculated_at > inference_fresh_until
            or output_valid_until > manifest_fresh_until
            or output_valid_until > inference_fresh_until
        ):
            raise ValueError("concrete fit knowledge is stale for its publication interval")
        return validity_policy

    @staticmethod
    def _validate_finite_dataset(dataset: PITResearchDataset) -> None:
        for row in dataset.rows:
            if not row.target_value.is_finite() or any(
                not proxy.value.is_finite() for proxy in row.proxies
            ):
                raise ValueError("PIT design contains a non-finite value")
        if dataset.inference_row is None or any(
            not proxy.value.is_finite() for proxy in dataset.inference_row.proxies
        ):
            raise ValueError("PIT inference row contains a non-finite value")

    @staticmethod
    def _arrays(
        row_ids: tuple[str, ...],
        rows: dict[str, PITResearchRow],
        candidate_codes: tuple[str, ...],
    ) -> tuple[FloatArray, FloatArray]:
        selected = tuple(rows[row_id] for row_id in row_ids)
        features = np.asarray(
            [
                [float(row.proxy_value(asset_code)) for asset_code in candidate_codes]
                for row in selected
            ],
            dtype=np.float64,
        )
        target = np.asarray([float(row.target_value) for row in selected], dtype=np.float64)
        if not np.all(np.isfinite(features)) or not np.all(np.isfinite(target)):
            raise ValueError("PIT design contains non-finite numerical values")
        return features, target

    def _fit(self, features: FloatArray, target: FloatArray, alpha: Decimal) -> _ModelFit:
        if features.shape[0] < 2 or features.shape[1] == 0:
            raise ValueError("Lasso fit requires multiple rows and features")
        if np.any(np.ptp(features, axis=0) <= float(self._config.zero_tolerance)):
            raise ValueError("constant feature is not admissible")
        scaler = StandardScaler(copy=True, with_mean=True, with_std=True)
        standardized = scaler.fit_transform(features)
        model = Lasso(
            alpha=float(alpha),
            fit_intercept=True,
            max_iter=self._config.max_iterations,
            tol=float(self._config.tolerance),
            selection="cyclic",
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            try:
                model.fit(standardized, target)
            except ConvergenceWarning as exc:
                raise ValueError("Lasso failed to converge") from exc
        n_iter = int(model.n_iter_)
        raw_dual_gap = float(model.dual_gap_)
        numerical_scale = max(
            1.0,
            float(np.mean(np.square(target))),
        )
        roundoff_floor = -float(np.finfo(np.float64).eps) * numerical_scale
        if n_iter < 0 or n_iter > self._config.max_iterations:
            raise ValueError("Lasso reported an invalid iteration budget")
        if not np.isfinite(raw_dual_gap) or raw_dual_gap < roundoff_floor:
            raise ValueError("Lasso dual-gap convergence evidence is invalid")
        coefficients = np.asarray(model.coef_, dtype=np.float64)
        coefficients[np.abs(coefficients) <= float(self._config.zero_tolerance)] = 0.0
        selected_indices = tuple(int(index) for index in np.flatnonzero(coefficients))
        denominator = float(np.sum(np.abs(coefficients)))
        weights = (
            coefficients / denominator
            if denominator > 0
            else np.zeros_like(coefficients, dtype=np.float64)
        )
        if not np.all(np.isfinite(weights)) or not np.isfinite(float(model.intercept_)):
            raise ValueError("Lasso produced non-finite parameters")
        return _ModelFit(scaler, model, coefficients, weights, selected_indices)

    def _score(self, actual: FloatArray, predicted: FloatArray, metric: str) -> Decimal:
        if metric == "validation_mean_squared_error":
            return _decimal(np.mean(np.square(actual - predicted)))
        return _decimal(self._correlation(actual, predicted))

    @staticmethod
    def _correlation(actual: FloatArray, predicted: FloatArray) -> float:
        if actual.size < 2 or np.ptp(actual) == 0 or np.ptp(predicted) == 0:
            raise ValueError("information coefficient requires non-constant vectors")
        value = float(np.corrcoef(actual, predicted)[0, 1])
        if not np.isfinite(value):
            raise ValueError("information coefficient is non-finite")
        return value

    def _calculate_fold(
        self,
        *,
        binding: ExecutionFoldBinding,
        rows: dict[str, PITResearchRow],
        candidate_codes: tuple[str, ...],
        request: NestedCVExecutionRequest,
    ) -> _FoldCalculation:
        fold = binding
        inner_scores: list[ExternalInnerFoldScore] = []
        totals = {alpha: Decimal("0") for alpha in request.alpha_grid}
        for inner in fold.inner_folds:
            train_x, train_y = self._arrays(inner.training_row_ids, rows, candidate_codes)
            validation_x, validation_y = self._arrays(
                inner.validation_row_ids, rows, candidate_codes
            )
            alpha_scores: list[ExternalAlphaScore] = []
            for alpha in request.alpha_grid:
                fit = self._fit(train_x, train_y, alpha)
                prediction = np.asarray(
                    fit.model.predict(fit.scaler.transform(validation_x)), dtype=np.float64
                )
                score = self._score(validation_y, prediction, request.optimization_metric)
                totals[alpha] += score
                alpha_scores.append(ExternalAlphaScore(alpha=alpha, score=score))
            inner_scores.append(
                ExternalInnerFoldScore(
                    inner_fold_id=inner.fold_id,
                    alpha_scores=tuple(alpha_scores),
                )
            )
        best = (
            min(totals.values())
            if request.optimization_direction is OptimizationDirection.MINIMIZE
            else max(totals.values())
        )
        selected_alpha = min(alpha for alpha, score in totals.items() if score == best)
        train_x, train_y = self._arrays(fold.outer_training_row_ids, rows, candidate_codes)
        validation_x, validation_y = self._arrays(
            fold.outer_validation_row_ids, rows, candidate_codes
        )
        evaluation_fit = self._fit(train_x, train_y, selected_alpha)
        train_prediction = np.asarray(
            evaluation_fit.model.predict(evaluation_fit.scaler.transform(train_x)),
            dtype=np.float64,
        )
        validation_prediction = np.asarray(
            evaluation_fit.model.predict(evaluation_fit.scaler.transform(validation_x)),
            dtype=np.float64,
        )
        final_x = np.concatenate((train_x, validation_x), axis=0)
        final_y = np.concatenate((train_y, validation_y), axis=0)
        final_fit = self._fit(final_x, final_y, selected_alpha)
        oos_x, oos_y = self._arrays(fold.outer_oos_row_ids, rows, candidate_codes)
        oos_prediction = np.asarray(
            final_fit.model.predict(final_fit.scaler.transform(oos_x)), dtype=np.float64
        )
        coefficients = tuple(
            ExternalProxyCoefficient(
                asset_code=asset_code,
                lasso_coefficient=_decimal(final_fit.coefficients[index]),
                factor_weight=_decimal(final_fit.weights[index]),
            )
            for index, asset_code in enumerate(candidate_codes)
        )
        concrete = self._ols_evidence(
            final_x=final_x,
            final_y=final_y,
            fit=final_fit,
            candidate_codes=candidate_codes,
        )
        selection = ExternalOuterFoldSelectionEvidence.create(
            fold_id=fold.fold_id,
            request_design_hash=fold.design_hash,
            selected_alpha=selected_alpha,
            inner_scores=tuple(inner_scores),
            final_fit_row_ids=(
                *fold.outer_training_row_ids,
                *fold.outer_validation_row_ids,
            ),
            final_fit_as_of=fold.selection_as_of,
            coefficients=coefficients,
            concrete_fit=concrete,
        )
        return _FoldCalculation(
            selection=selection,
            final_fit=final_fit,
            oos_predictions=tuple(
                ExternalFoldPrediction(
                    fold_id=fold.fold_id,
                    row_id=row_id,
                    predicted_value=_decimal(oos_prediction[index]),
                )
                for index, row_id in enumerate(fold.outer_oos_row_ids)
            ),
            train_actual=train_y,
            train_predicted=train_prediction,
            validation_actual=validation_y,
            validation_predicted=validation_prediction,
            oos_actual=oos_y,
            oos_predicted=oos_prediction,
        )

    def _ols_evidence(
        self,
        *,
        final_x: FloatArray,
        final_y: FloatArray,
        fit: _ModelFit,
        candidate_codes: tuple[str, ...],
    ) -> ExternalConcreteFitEvidence:
        standardized = np.asarray(fit.scaler.transform(final_x), dtype=np.float64)
        selected_x = standardized[:, fit.selected_indices]
        design = np.asarray(sm.add_constant(selected_x, has_constant="add"), dtype=np.float64)
        result = sm.OLS(final_y, design, missing="raise").fit()
        params = np.asarray(result.params, dtype=np.float64)
        errors = np.asarray(result.bse, dtype=np.float64)
        statistics = np.asarray(result.tvalues, dtype=np.float64)
        p_values = np.asarray(result.pvalues, dtype=np.float64)
        diagnostics = tuple(
            ExternalOLSCoefficientDiagnostic(
                asset_code=candidate_codes[feature_index],
                coefficient=_decimal(params[position + 1]),
                standard_error=_decimal(errors[position + 1]),
                t_statistic=_decimal(statistics[position + 1]),
                p_value=_decimal(p_values[position + 1]),
            )
            for position, feature_index in enumerate(fit.selected_indices)
        )
        return ExternalConcreteFitEvidence.create(
            estimator_version=self._estimator_version,
            standardization_version=self._standardization_version,
            lasso_intercept=_decimal(fit.model.intercept_),
            standardization=tuple(
                ExternalFeatureStandardization(
                    asset_code=asset_code,
                    mean=_decimal(fit.scaler.mean_[index]),
                    scale=_decimal(fit.scaler.scale_[index]),
                )
                for index, asset_code in enumerate(candidate_codes)
            ),
            ols_sample_count=int(result.nobs),
            ols_rank=int(result.model.rank),
            ols_intercept=_decimal(params[0]),
            ols_intercept_standard_error=_decimal(errors[0]),
            ols_intercept_p_value=_decimal(p_values[0]),
            ols_adjusted_r_squared=_decimal(result.rsquared_adj),
            ols_bic=_decimal(result.bic),
            ols_coefficients=diagnostics,
        )

    @staticmethod
    def _portfolio_diagnostics(
        selections: tuple[ExternalOuterFoldSelectionEvidence, ...],
    ) -> tuple[Decimal, Decimal]:
        sets = [
            {item.asset_code for item in fold.coefficients if item.lasso_coefficient != 0}
            for fold in selections
        ]
        if len(sets) < 2:
            raise ValueError("portfolio stability requires at least two outer folds")
        similarities = [
            Decimal(len(left & right)) / Decimal(len(left | right))
            for left, right in zip(sets, sets[1:], strict=False)
        ]
        stability = sum(similarities, start=Decimal("0")) / Decimal(len(similarities))
        previous = {code: Decimal("0") for code in sets[0] | set().union(*sets[1:])}
        turnovers: list[Decimal] = []
        for fold in selections:
            current = {item.asset_code: item.factor_weight for item in fold.coefficients}
            turnovers.append(
                sum(
                    (
                        abs(current.get(code, Decimal("0")) - previous.get(code, Decimal("0")))
                        for code in previous
                    ),
                    start=Decimal("0"),
                )
                / Decimal("2")
            )
            previous = current
        return stability, sum(turnovers, start=Decimal("0")) / Decimal(len(turnovers))

    def _metrics(
        self,
        segment: SampleSegment,
        calculations: tuple[_FoldCalculation, ...],
        actual_name: str,
        predicted_name: str,
        parameter_count: int,
        stability: Decimal,
        turnover: Decimal,
        cost: Decimal,
    ) -> EvaluationMetrics:
        actual = np.concatenate(tuple(getattr(item, actual_name) for item in calculations), axis=0)
        predicted = np.concatenate(
            tuple(getattr(item, predicted_name) for item in calculations), axis=0
        )
        residual = actual - predicted
        total = float(np.sum(np.square(actual - np.mean(actual))))
        if total == 0:
            raise ValueError("evaluation target is constant")
        r_squared = 1.0 - float(np.sum(np.square(residual))) / total
        denominator = actual.size - parameter_count - 1
        if denominator <= 0:
            raise ValueError("adjusted R-squared requires more observations")
        adjusted = 1.0 - (1.0 - r_squared) * (actual.size - 1) / denominator
        return EvaluationMetrics(
            segment=segment,
            sample_count=int(actual.size),
            r_squared=_decimal(r_squared),
            adjusted_r_squared=_decimal(adjusted),
            information_coefficient=_decimal(self._correlation(actual, predicted)),
            stability_score=stability,
            turnover=turnover,
            transaction_cost=cost,
        )

    @staticmethod
    def _significance_summary(evidence: ExternalConcreteFitEvidence) -> str:
        values = ", ".join(
            f"{item.asset_code}:p={item.p_value}" for item in evidence.ols_coefficients
        )
        return f"OLS refit on standardized selected features; {values}."


__all__ = ["SklearnNestedCVFittingConfig", "SklearnNestedCVLassoRunner"]

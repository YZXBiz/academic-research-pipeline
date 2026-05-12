"""Tests for plan-alignment verification."""
from __future__ import annotations

from academic_pipeline.models.experiment import (
    DatasetSpec,
    ExperimentPlan,
    MethodSpec,
)
from academic_pipeline.tools.execution.sanity import verify_plan_alignment


def _make_plan() -> ExperimentPlan:
    return ExperimentPlan(
        research_question="Test",
        hypothesis="Test",
        experiment_type="benchmark",
        dataset_sources=[
            DatasetSpec(
                name="Iris",
                source="huggingface",
                download_instruction="from datasets import load_dataset; ds = load_dataset('scikit-learn/iris')",
                expected_shape="150x4",
                target_column="target",
            )
        ],
        baseline_methods=[
            MethodSpec(name="LR", implementation="LogisticRegression()", is_baseline=True)
        ],
        proposed_methods=[
            MethodSpec(name="AutoGluon", implementation="TabularPredictor(label='target')", is_baseline=False)
        ],
        evaluation_metrics=["accuracy", "f1_macro"],
        success_criteria=">2% improvement",
        required_figures=["performance_bar_chart"],
        python_packages=["sklearn", "xgboost"],
    )


def test_aligned_code_passes():
    code = '''
import json
from datasets import load_dataset
ds = load_dataset("scikit-learn/iris")
from sklearn.linear_model import LogisticRegression
from autogluon.tabular import TabularPredictor
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.metrics import f1_score
from scipy.stats import wilcoxon
import matplotlib.pyplot as plt
plt.savefig("figures/performance_bar_chart.png")
with open("results.json", "w") as f:
    json.dump({"metrics": {"accuracy": 0.9, "f1_macro": 0.85}}, f)
'''
    result = verify_plan_alignment(code, _make_plan())
    assert result.aligned is True


def test_missing_method_detected():
    code = '''
import json
from datasets import load_dataset
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from scipy.stats import wilcoxon
import matplotlib.pyplot as plt
plt.savefig("figures/performance_bar_chart.png")
with open("results.json", "w") as f:
    json.dump({}, f)
'''
    result = verify_plan_alignment(code, _make_plan())
    assert result.aligned is False
    assert "TabularPredictor" in result.missing_methods


def test_missing_cv_detected():
    code = '''
import json
from datasets import load_dataset
from sklearn.linear_model import LogisticRegression
from autogluon.tabular import TabularPredictor
from scipy.stats import wilcoxon
import matplotlib.pyplot as plt
plt.savefig("figures/performance_bar_chart.png")
with open("results.json", "w") as f:
    json.dump({"metrics": {"accuracy": 0.9, "f1_macro": 0.85}}, f)
'''
    result = verify_plan_alignment(code, _make_plan())
    assert result.aligned is False
    assert result.missing_cross_validation is True


def test_missing_stat_test_detected():
    code = '''
import json
from datasets import load_dataset
from sklearn.linear_model import LogisticRegression
from autogluon.tabular import TabularPredictor
from sklearn.model_selection import StratifiedKFold
import matplotlib.pyplot as plt
plt.savefig("figures/performance_bar_chart.png")
with open("results.json", "w") as f:
    json.dump({"metrics": {"accuracy": 0.9, "f1_macro": 0.85}}, f)
'''
    result = verify_plan_alignment(code, _make_plan())
    assert result.aligned is False
    assert result.missing_statistical_tests is True


def test_missing_figure_detected():
    code = '''
import json
from datasets import load_dataset
from sklearn.linear_model import LogisticRegression
from autogluon.tabular import TabularPredictor
from sklearn.model_selection import StratifiedKFold
from scipy.stats import wilcoxon
with open("results.json", "w") as f:
    json.dump({"metrics": {"accuracy": 0.9, "f1_macro": 0.85}}, f)
'''
    result = verify_plan_alignment(code, _make_plan())
    assert result.aligned is False
    assert "performance_bar_chart" in result.missing_figures

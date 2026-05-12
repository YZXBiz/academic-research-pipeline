"""Tests for dataset URL verification and email alert."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from academic_pipeline.models.experiment import DatasetSpec
from academic_pipeline.tools.execution.sanity import verify_dataset_urls


class TestDatasetUrlVerification:
    def test_sklearn_source_passes_without_network(self):
        datasets = [
            DatasetSpec(
                name="Iris",
                source="sklearn",
                download_instruction="load_iris()",
                expected_shape="150x4",
                target_column="target",
            )
        ]
        result = verify_dataset_urls(datasets)
        assert result.all_verified is True
        assert result.failed_datasets == []

    def test_ucimlrepo_source_passes(self):
        datasets = [
            DatasetSpec(
                name="Wine",
                source="ucimlrepo",
                download_instruction="fetch_ucirepo(id=109)",
                expected_shape="178x13",
                target_column="target",
            )
        ]
        result = verify_dataset_urls(datasets)
        assert result.all_verified is True

    def test_huggingface_source_passes(self):
        datasets = [
            DatasetSpec(
                name="IMDB",
                source="huggingface",
                download_instruction="load_dataset('imdb')",
                expected_shape="50000x2",
                target_column="label",
            )
        ]
        result = verify_dataset_urls(datasets)
        assert result.all_verified is True

    @patch("academic_pipeline.tools.execution.sanity._check_url_reachable")
    def test_url_source_verified(self, mock_check):
        mock_check.return_value = True
        datasets = [
            DatasetSpec(
                name="Cox",
                source="url",
                download_instruction="https://example.com/data.txt",
                expected_shape="100x5",
                target_column="sales",
            )
        ]
        result = verify_dataset_urls(datasets)
        assert result.all_verified is True

    @patch("academic_pipeline.tools.execution.sanity._check_url_reachable")
    def test_url_source_fails(self, mock_check):
        mock_check.return_value = False
        datasets = [
            DatasetSpec(
                name="Fake",
                source="url",
                download_instruction="https://example.com/nonexistent.csv",
                expected_shape="100x5",
                target_column="target",
            )
        ]
        result = verify_dataset_urls(datasets)
        assert result.all_verified is False
        assert "Fake" in result.failed_datasets

    def test_empty_datasets_fails(self):
        result = verify_dataset_urls([])
        assert result.all_verified is False


class TestEmailAlert:
    @patch("smtplib.SMTP")
    def test_send_alert_with_config(self, mock_smtp):
        from academic_pipeline.tools.execution.sanity import send_dataset_alert

        mock_config = MagicMock()
        mock_config.experiment_smtp_server = "test.smtp.com"
        mock_config.experiment_smtp_port = 25
        mock_config.experiment_alert_email = "test@test.com"
        mock_config.experiment_alert_sender = "sender@test.com"
        asyncio.run(send_dataset_alert("test topic", ["missing_data"], mock_config))
        mock_smtp.assert_called_once_with("test.smtp.com", 25)

    def test_send_alert_skips_without_config(self):
        from academic_pipeline.tools.execution.sanity import send_dataset_alert

        mock_config = MagicMock()
        mock_config.experiment_smtp_server = ""
        mock_config.experiment_alert_email = ""
        # Should not raise — just logs and returns
        asyncio.run(send_dataset_alert("test topic", ["missing"], mock_config))

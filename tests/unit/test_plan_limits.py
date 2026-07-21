"""Unit tests for per-plan upload limits."""

from __future__ import annotations

import pytest

from app.config.plans import PLAN_LIMITS, limits_for_plan
from app.exceptions.files import TooManyFilesError
from app.services.file_validation import validate_file_count


class TestLimitsForPlan:
    def test_known_plans_resolve(self):
        for name, limits in PLAN_LIMITS.items():
            assert limits_for_plan(name) is limits

    def test_anonymous_gets_free_tier(self):
        assert limits_for_plan(None) is PLAN_LIMITS["free"]

    def test_unknown_plan_falls_back_to_free(self):
        assert limits_for_plan("platinum") is PLAN_LIMITS["free"]

    def test_case_insensitive(self):
        assert limits_for_plan("Pro") is PLAN_LIMITS["pro"]

    def test_tiers_are_ordered(self):
        free, basic, pro = (
            PLAN_LIMITS["free"],
            PLAN_LIMITS["basic"],
            PLAN_LIMITS["pro"],
        )
        assert free.max_files < basic.max_files < pro.max_files
        assert free.max_file_size_mb < basic.max_file_size_mb < pro.max_file_size_mb
        assert free.max_total_size_mb < basic.max_total_size_mb < pro.max_total_size_mb

    def test_enterprise_gets_top_tier(self):
        assert PLAN_LIMITS["enterprise"].max_files == PLAN_LIMITS["pro"].max_files
        assert (
            PLAN_LIMITS["enterprise"].max_total_size_mb
            == PLAN_LIMITS["pro"].max_total_size_mb
        )

    def test_byte_properties(self):
        free = PLAN_LIMITS["free"]
        assert free.max_file_size_bytes == free.max_file_size_mb * 1024 * 1024
        assert free.max_total_size_bytes == free.max_total_size_mb * 1024 * 1024


class TestPlanFileCount:
    def test_free_batch_limit_enforced(self):
        free = limits_for_plan("free")
        validate_file_count(free.max_files, max_files=free.max_files)
        with pytest.raises(TooManyFilesError):
            validate_file_count(free.max_files + 1, max_files=free.max_files)

    def test_pro_allows_larger_batches(self):
        pro = limits_for_plan("pro")
        validate_file_count(pro.max_files, max_files=pro.max_files)

from datetime import date

from app.domain.hard_filters import FilterStatus, RulesConfig, evaluate_hard_filters


def eligible_application(**overrides):
    application = {
        "adult_count": 2,
        "child_count": 1,
        "child_details": [{"first_name": "Maya", "last_name": "Garcia", "age": 5}],
        "applicant_age": 35,
        "co_applicant_age": 33,
        "household_income": 100_000,
        "applicant_income": 55_000,
        "co_applicant_income": 45_000,
        "has_real_estate": False,
        "co_applicant_name": "Morgan Wilson",
        "co_applicant_phone": "778-555-2000",
        "co_applicant_email": "co@example.com",
        "applicant_email": "test@example.com",
        "form_submission_email": "test@example.com",
        "applicant_employment_start": date(2020, 1, 15),
        "co_applicant_employment_start": date(2021, 3, 1),
    }
    application.update(overrides)
    return application


def reason_codes(result):
    return {reason.code for reason in result.reasons}


def test_two_bedroom_eligible_household_passes() -> None:
    result = evaluate_hard_filters(eligible_application())

    assert result.status == FilterStatus.ELIGIBLE
    assert result.reasons == []





def test_income_outside_configured_range_is_filtered_out() -> None:
    rules = RulesConfig(min_income=70_000, max_income=150_000)

    low_result = evaluate_hard_filters(eligible_application(household_income=69_999), rules)
    high_result = evaluate_hard_filters(eligible_application(household_income=150_001), rules)

    assert low_result.status == FilterStatus.FILTERED_OUT
    assert "income_below_range" in reason_codes(low_result)
    assert high_result.status == FilterStatus.FILTERED_OUT
    assert "income_above_range" in reason_codes(high_result)




def test_real_estate_ownership_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(has_real_estate=True))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "owns_real_estate" in reason_codes(result)




def test_child_age_over_max_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(
        child_details=[{"first_name": "Alex", "last_name": "Smith", "age": 18}],
    ))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "child_age_over_max" in reason_codes(result)


def test_child_age_17_passes() -> None:
    result = evaluate_hard_filters(eligible_application(
        child_details=[{"first_name": "Alex", "last_name": "Smith", "age": 17}],
    ))

    assert result.status == FilterStatus.ELIGIBLE


def test_configurable_max_child_age() -> None:
    # A co-op housing teens could raise the ceiling; a 19-year-old then passes.
    rules = RulesConfig(max_child_age=20)
    result = evaluate_hard_filters(
        eligible_application(
            child_details=[{"first_name": "Alex", "last_name": "Smith", "age": 19}],
        ),
        rules,
    )

    assert "child_age_over_max" not in reason_codes(result)


def test_too_few_children_is_filtered_out() -> None:
    result = evaluate_hard_filters(
        eligible_application(child_count=0, child_details=[])
    )

    assert result.status == FilterStatus.FILTERED_OUT
    assert "too_few_children" in reason_codes(result)


def test_too_many_children_is_filtered_out() -> None:
    result = evaluate_hard_filters(
        eligible_application(
            child_count=5,
            child_details=[
                {"first_name": f"Kid{i}", "last_name": "Garcia", "age": 5 + i}
                for i in range(5)
            ],
        )
    )

    assert result.status == FilterStatus.FILTERED_OUT
    assert "too_many_children" in reason_codes(result)


def test_configurable_children_bounds() -> None:
    # A childless-allowed co-op: min 0 lets a 0-child household through.
    rules = RulesConfig(min_children=0)
    result = evaluate_hard_filters(
        eligible_application(child_count=0, child_details=[]), rules
    )

    assert "too_few_children" not in reason_codes(result)


def test_applicant_under_min_age_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(applicant_age=17))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "applicant_under_min_age" in reason_codes(result)


def test_co_applicant_under_min_age_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(co_applicant_age=14))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "co_applicant_under_min_age" in reason_codes(result)


def test_co_applicant_age_none_does_not_trigger() -> None:
    result = evaluate_hard_filters(eligible_application(
        co_applicant_age=None,
        co_applicant_name=None,
        co_applicant_phone=None,
        co_applicant_email=None,
        adult_count=1,
        applicant_income=100_000,
        co_applicant_income=None,
    ))

    assert result.status == FilterStatus.ELIGIBLE


def test_child_count_mismatch_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(
        child_count=2,
        child_details=[{"first_name": "Maya", "last_name": "Garcia", "age": 5}],
    ))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "child_count_mismatch" in reason_codes(result)


def test_child_count_matches_complete_blocks_passes() -> None:
    result = evaluate_hard_filters(eligible_application(
        child_count=2,
        child_details=[
            {"first_name": "Maya", "last_name": "Garcia", "age": 5},
            {"first_name": "Leo", "last_name": "Garcia", "age": 3},
        ],
    ))

    assert "child_count_mismatch" not in reason_codes(result)


def test_partial_child_block_not_counted_as_complete() -> None:
    result = evaluate_hard_filters(eligible_application(
        child_count=1,
        child_details=[
            {"first_name": "Maya", "last_name": "Garcia", "age": 5},
            {"first_name": "Kira", "last_name": None, "age": None},
        ],
    ))

    assert "child_count_mismatch" not in reason_codes(result)


def test_child_age_exceeds_parent_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(
        applicant_age=25,
        co_applicant_age=25,
        child_details=[{"first_name": "Old", "last_name": "Kid", "age": 25}],
    ))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "child_age_exceeds_parent" in reason_codes(result)


def test_income_arithmetic_mismatch_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(
        applicant_income=50_000,
        co_applicant_income=45_000,
        household_income=120_000,
    ))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "income_arithmetic_mismatch" in reason_codes(result)


def test_income_arithmetic_exact_match_passes() -> None:
    result = evaluate_hard_filters(eligible_application(
        applicant_income=50_000,
        co_applicant_income=45_000,
        household_income=95_000,
    ))

    assert "income_arithmetic_mismatch" not in reason_codes(result)


def test_income_arithmetic_off_by_any_amount_is_filtered_out() -> None:
    # No tolerance: even a $1 discrepancy is a mismatch.
    result = evaluate_hard_filters(eligible_application(
        applicant_income=50_000,
        co_applicant_income=45_000,
        household_income=95_001,
    ))

    assert "income_arithmetic_mismatch" in reason_codes(result)


def test_negative_age_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(
        child_details=[{"first_name": "Bug", "last_name": "Test", "age": -2}],
    ))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "negative_number" in reason_codes(result)


def test_negative_income_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(applicant_income=-5000))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "negative_number" in reason_codes(result)




def test_future_employment_start_is_filtered_out() -> None:
    rules = RulesConfig(today=date(2026, 6, 11))
    result = evaluate_hard_filters(
        eligible_application(applicant_employment_start=date(2027, 3, 1)),
        rules,
    )

    assert result.status == FilterStatus.FILTERED_OUT
    assert "future_employment_start" in reason_codes(result)


def test_co_applicant_incomplete_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(
        co_applicant_name="Partial Person",
        co_applicant_age=30,
        co_applicant_phone=None,
        co_applicant_email=None,
    ))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "co_applicant_incomplete" in reason_codes(result)






def test_disabled_rule_is_skipped() -> None:
    rules = RulesConfig(disabled_rules=("owns_real_estate",))
    result = evaluate_hard_filters(eligible_application(has_real_estate=True), rules)

    assert result.status == FilterStatus.ELIGIBLE
    assert "owns_real_estate" not in reason_codes(result)


def test_disabled_rule_skips_filtered_out() -> None:
    rules = RulesConfig(disabled_rules=("child_count_mismatch",))
    result = evaluate_hard_filters(eligible_application(
        child_count=2,
        child_details=[{"first_name": "Maya", "last_name": "Garcia", "age": 5}],
    ), rules)

    assert result.status == FilterStatus.ELIGIBLE
    assert "child_count_mismatch" not in reason_codes(result)


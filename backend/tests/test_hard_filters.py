from app.domain.hard_filters import FilterStatus, UnitRules, evaluate_hard_filters


def eligible_application(**overrides):
    application = {
        "adult_count": 2,
        "child_count": 1,
        "household_income": 100_000,
        "has_real_estate": False,
        "dog_count": 1,
        "cat_count": 1,
        "other_pet_count": 0,
    }
    application.update(overrides)
    return application


def reason_codes(result):
    return {reason.code for reason in result.reasons}


def test_two_bedroom_eligible_household_passes() -> None:
    result = evaluate_hard_filters(eligible_application())

    assert result.status == FilterStatus.ELIGIBLE
    assert result.reasons == []


def test_three_adults_are_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(adult_count=3))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "too_many_adults" in reason_codes(result)


def test_two_bedroom_without_child_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(child_count=0))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "household_size_ineligible" in reason_codes(result)


def test_unclear_household_is_needs_review() -> None:
    result = evaluate_hard_filters(eligible_application(adult_count=None))

    assert result.status == FilterStatus.NEEDS_REVIEW
    assert "household_unclear" in reason_codes(result)


def test_income_outside_configured_range_is_filtered_out() -> None:
    rules = UnitRules(min_income=70_000, max_income=150_000)

    low_result = evaluate_hard_filters(eligible_application(household_income=69_999), rules)
    high_result = evaluate_hard_filters(eligible_application(household_income=150_001), rules)

    assert low_result.status == FilterStatus.FILTERED_OUT
    assert "income_below_range" in reason_codes(low_result)
    assert high_result.status == FilterStatus.FILTERED_OUT
    assert "income_above_range" in reason_codes(high_result)


def test_unclear_income_is_needs_review() -> None:
    result = evaluate_hard_filters(eligible_application(household_income="unknown"))

    assert result.status == FilterStatus.NEEDS_REVIEW
    assert "income_unclear" in reason_codes(result)


def test_real_estate_ownership_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(has_real_estate=True))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "owns_real_estate" in reason_codes(result)


def test_one_dog_and_one_cat_are_allowed() -> None:
    result = evaluate_hard_filters(eligible_application(dog_count=1, cat_count=1))

    assert result.status == FilterStatus.ELIGIBLE


def test_extra_pet_is_filtered_out() -> None:
    result = evaluate_hard_filters(eligible_application(dog_count=2))

    assert result.status == FilterStatus.FILTERED_OUT
    assert "pet_rule_violation" in reason_codes(result)


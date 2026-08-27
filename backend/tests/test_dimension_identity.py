

from app.ai.schemas import (
    DecomposedDimension,
    DecompositionReport,
    DimensionMatch,
    DimensionMatchReport,
    PoolDimension,
    PoolDimensionReport,
)
from app.db.models import UserRole
from tests.ranking_support import (
    a_pattern_report,
    add_eligible,
    setup_app,
)


def test_fan_out_seeds_only_worker_0_the_rest_stay_blind() -> None:
    # Proposals steer ONE discoverer (worker 0); workers 1..K-1 stay blind, preserving
    # K-1 independent samples. Assert exactly one of K prompts carries the proposal.
    from app.ai.dimension_discovery import DiscoverySeeds, discover_patterns_fanout

    _app, db, provider = setup_app(role=UserRole.MEMBER)
    add_eligible(db, email="a@x.com", raw_hash="h1")
    from app.ai.dimension_discovery import eligible_applications

    pool = eligible_applications(db)
    k = 4
    for _ in range(k):
        provider.queue(a_pattern_report())

    from app.schemas.settings import AppSettings

    seeds = DiscoverySeeds(proposed=["families who'd use the playground"])
    discover_patterns_fanout(
        provider, applications=pool, settings=AppSettings(), k=k, seeds=seeds,
    )
    discovery_calls = [c for c in provider.calls if "<applicant_pool>" in c.prompt]
    assert len(discovery_calls) == k
    seeded = [c for c in discovery_calls if "families who'd use the playground" in c.prompt]
    assert len(seeded) == 1, "exactly one discoverer should carry the proposal"


def test_enforce_committee_requests_guarantees_an_unsurfaced_kept_axis() -> None:
    # A kept axis that NO discovery report re-surfaced (so it's absent from the settled
    # set) must be re-added by the guard — a kept axis is never dropped. But it re-adds
    # as an ORDINARY dimension: from_committee_request stays false (it's a carried axis
    # the committee tiered on a prior run, not a fresh ask this run).
    from app.ai.dimension_decomposition import enforce_committee_requests

    kept_axis = PoolDimension(
        key="participation_commitment", name="Participation commitment",
        definition="Willingness to do shared work.", high_end="high", low_end="low", why_it_differentiates="varies",
    )
    # Decomposition settled on an unrelated axis only.
    settled = DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key="skills_offered", name="Skills offered", definition="trades",
                high_end="high", low_end="low",
                source_keys=["skills_offered"],
                decision="kept",
            ),
        ],
    )
    corrected, folded = enforce_committee_requests(settled, [], kept=[kept_axis])
    keys = {d.key for d in corrected.dimensions}
    assert "participation_commitment" in keys  # re-added, not lost
    readded = next(d for d in corrected.dimensions if d.key == "participation_commitment")
    assert readded.from_committee_request is False  # kept axis carries no request flag
    assert folded == []  # kept standalone, not folded into another axis


def test_enforce_committee_requests_flag_is_authoritative_for_kept_and_plain_axes() -> None:
    # The flag is recomputed from scratch: true iff the settled axis absorbed a fresh
    # PROPOSAL this run, false otherwise. So a model that stamps from_committee_request
    # on a kept axis (surfaced by decomposition) or a plain discovered axis is overruled —
    # only a real proposal keeps the flag, guaranteeing it clears on the next run.
    from app.ai.dimension_decomposition import enforce_committee_requests

    kept_axis = PoolDimension(
        key="participation_commitment", name="Participation commitment",
        definition="Willingness to do shared work.", high_end="high", low_end="low", why_it_differentiates="varies",
    )
    # The model surfaced the kept axis AND (wrongly) stamped the flag on it and on a
    # plain discovered axis. Neither should keep the flag — no proposal this run.
    settled = DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key="participation_commitment", name="Participation commitment",
                definition="Willingness to do shared work.", high_end="high", low_end="low",
                source_keys=["participation_commitment"],
                from_committee_request=True,  # stray stamp — guard must strip it
                decision="kept",
            ),
            DecomposedDimension(
                key="skills_offered", name="Skills offered", definition="trades",
                high_end="high", low_end="low",
                source_keys=["skills_offered"],
                from_committee_request=True,  # stray stamp — guard must strip it
                decision="kept",
            ),
        ],
    )
    corrected, folded = enforce_committee_requests(settled, [], kept=[kept_axis])
    by_key = {d.key: d for d in corrected.dimensions}
    assert by_key["participation_commitment"].from_committee_request is False
    assert by_key["skills_offered"].from_committee_request is False
    assert folded == []


def test_enforce_committee_requests_strips_stray_flag_when_nothing_asked() -> None:
    # No proposals and no kept axes: the flag is still made authoritative, so a model
    # that stamps from_committee_request on its own is overruled (nothing was asked).
    from app.ai.dimension_decomposition import enforce_committee_requests

    settled = DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key="skills_offered", name="Skills offered", definition="trades",
                high_end="high", low_end="low", source_keys=["skills_offered"],
                from_committee_request=True,  # stray — no ask this run
                decision="kept",
            ),
        ],
    )
    corrected, folded = enforce_committee_requests(settled, [], kept=[])
    assert corrected.dimensions[0].from_committee_request is False
    assert folded == []


def test_adopt_matched_keys_dedupes_a_d9_readd_colliding_with_a_matched_key() -> None:
    # A kept axis re-added by the D9 guard under its canonical key can collide with a
    # DRIFTED re-discovery of the same concept that ALSO matches back to that key. A key
    # must be unique (cache identity), so the matched dimension wins and the redundant
    # re-add is dropped — never two dims sharing a key (which would 500 on the cache's
    # UNIQUE constraint).
    from app.services.ranking.identity import adopt_matched_keys

    prior = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="Participation commitment",
                      definition="prior text", high_end="high", low_end="low", why_it_differentiates="v"),
    ])
    # This run: a drifted re-discovery of the same axis + the D9-re-added canonical key.
    report = PoolDimensionReport(dimensions=[
        PoolDimension(key="stated_participation", name="Stated participation",
                      definition="fresh text", high_end="high", low_end="low", why_it_differentiates="v"),
        PoolDimension(key="participation_commitment", name="Participation commitment",
                      definition="re-added", high_end="high", low_end="low", why_it_differentiates="v",
                      from_committee_request=True),
    ])
    adopted = adopt_matched_keys(
        report, {"stated_participation": "participation_commitment"}, prior
    )
    keys = [d.key for d in adopted.dimensions]
    assert keys == ["participation_commitment"]  # de-duped to one
    # The MATCHED dimension won — it carries the prior text the cached score pairs with.
    assert adopted.dimensions[0].definition == "prior text"


def test_adopt_matched_keys_collapses_two_twins_onto_one_prior() -> None:
    # Many-to-one: discovery re-carved ONE prior axis into TWO twins this run, and the
    # matcher recognized both as that prior concept. They must collapse into a SINGLE
    # dimension under the prior key (reusing its cached score), not survive as two axes
    # that double-weight one concept.
    from app.services.ranking.identity import adopt_matched_keys

    prior = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="Participation commitment",
                      definition="prior text", high_end="high", low_end="low", why_it_differentiates="v"),
    ])
    report = PoolDimensionReport(dimensions=[
        PoolDimension(key="committee_participation", name="Committee participation",
                      definition="fresh a", high_end="high", low_end="low", why_it_differentiates="v"),
        PoolDimension(key="workday_participation", name="Workday participation",
                      definition="fresh b", high_end="high", low_end="low", why_it_differentiates="v"),
    ])
    # BOTH twins map to the same prior key (the sanitizer now allows this).
    adopted = adopt_matched_keys(
        report,
        {"committee_participation": "participation_commitment",
         "workday_participation": "participation_commitment"},
        prior,
    )
    keys = [d.key for d in adopted.dimensions]
    assert keys == ["participation_commitment"]  # collapsed to one
    # The prior text (and its cached score) is what survives — not either fresh carving.
    assert adopted.dimensions[0].definition == "prior text"


def test_match_dimensions_allows_many_new_onto_one_prior() -> None:
    # The sanitizer keeps several new->same-old pairs (a re-carved prior axis), dropping
    # only a repeated NEW key or an unknown key. (Previously it forced strict one-to-one,
    # silently discarding the second twin -> a double-counted concept downstream.)
    from unittest.mock import MagicMock

    from app.ai.dimension_matching import match_dimensions
    from app.schemas.settings import AppSettings

    old = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="P", definition="d",
                      high_end="h", low_end="l", why_it_differentiates="v"),
    ])
    new = PoolDimensionReport(dimensions=[
        PoolDimension(key="committee_participation", name="A", definition="d",
                      high_end="h", low_end="l", why_it_differentiates="v"),
        PoolDimension(key="workday_participation", name="B", definition="d",
                      high_end="h", low_end="l", why_it_differentiates="v"),
    ])
    provider = MagicMock()
    provider.structured_output.return_value = MagicMock(
        output=DimensionMatchReport(matches=[
            DimensionMatch(new_key="committee_participation", old_key="participation_commitment"),
            DimensionMatch(new_key="workday_participation", old_key="participation_commitment"),
        ]),
        narrative=None,
        model_id="m",
        usage=MagicMock(input_tokens=1, output_tokens=1),
    )
    mapping, _narrative, _cost = match_dimensions(
        provider, old=old, new=new, settings=AppSettings()
    )
    assert mapping == {
        "committee_participation": "participation_commitment",
        "workday_participation": "participation_commitment",
    }


def test_match_dimensions_forces_self_match_over_a_wrong_llm_match() -> None:
    # A key present in BOTH lists (e.g. a committee-kept axis, injected at decomposition
    # under its exact prior key) IS its own prior axis by the frozen-key invariant. If the
    # LLM wrongly maps it onto a DIFFERENT prior key, the sanitizer overrides that to a
    # self-match — so the kept axis can never be matched away from itself and vanish.
    from unittest.mock import MagicMock

    from app.ai.dimension_matching import match_dimensions
    from app.schemas.settings import AppSettings

    old = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="P", definition="d",
                      high_end="h", low_end="l", why_it_differentiates="v"),
        PoolDimension(key="financial_stability", name="F", definition="d",
                      high_end="h", low_end="l", why_it_differentiates="v"),
    ])
    # The kept axis recurs under its exact key; a fresh axis is genuinely new.
    new = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="P", definition="d",
                      high_end="h", low_end="l", why_it_differentiates="v"),
    ])
    provider = MagicMock()
    provider.structured_output.return_value = MagicMock(
        # The model wrongly maps the kept key onto a DIFFERENT prior key.
        output=DimensionMatchReport(matches=[
            DimensionMatch(new_key="participation_commitment", old_key="financial_stability"),
        ]),
        narrative=None,
        model_id="m",
        usage=MagicMock(input_tokens=1, output_tokens=1),
    )
    mapping, _narrative, _cost = match_dimensions(
        provider, old=old, new=new, settings=AppSettings()
    )
    # Overridden to a self-match — NOT the wrong financial_stability mapping.
    assert mapping == {"participation_commitment": "participation_commitment"}


def test_adopt_self_matched_key_restores_frozen_prior_text() -> None:
    # A scored key the decomposer reworded (new text under the same key) must adopt its
    # FROZEN prior text wholesale — the cached score was computed against the prior text,
    # so name/definition/poles must all revert. (Self-match => adopt_matched_keys pulls the
    # prior dimension entirely; the decomposer's rewording is discarded.)
    from app.services.ranking.identity import adopt_matched_keys

    prior = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="Participation commitment",
                      definition="prior def", high_end="prior hi", low_end="prior lo",
                      why_it_differentiates="prior why"),
    ])
    # Same key, but the decomposer reworded everything.
    new = PoolDimensionReport(dimensions=[
        PoolDimension(key="participation_commitment", name="Reworded",
                      definition="reworded def", high_end="new hi", low_end="new lo",
                      why_it_differentiates="reworded why"),
    ])
    # match_dimensions would force the self-match; pass it explicitly here.
    adopted = adopt_matched_keys(
        new, {"participation_commitment": "participation_commitment"}, prior
    )
    dim = adopted.dimensions[0]
    assert dim.key == "participation_commitment"
    assert dim.name == "Participation commitment"  # frozen prior text, not "Reworded"
    assert dim.definition == "prior def"
    assert dim.high_end == "prior hi"
    assert dim.low_end == "prior lo"
    assert dim.why_it_differentiates == "prior why"


def test_settled_why_is_carried_from_source_not_decomposer() -> None:
    # The decomposer never sees the pool, so it does not write why_it_differentiates;
    # to_pool_report carries the real, pool-grounded why forward from the PRIMARY source
    # discovery axis (first source_key that resolves), including across a merge.
    from app.ai.dimension_decomposition import to_pool_report

    reports = [
        PoolDimensionReport(
            dimensions=[
                PoolDimension(
                    key="commitment_a", name="Commitment A",
                    definition="willingness to do shared work",
                    high_end="high", low_end="low", why_it_differentiates="Applicants range from eager volunteers to vague.",
                ),
                PoolDimension(
                    key="commitment_b", name="Commitment B",
                    definition="willingness to show up for work days",
                    high_end="high", low_end="low", why_it_differentiates="secondary carving why",
                ),
            ],
        ),
    ]
    settled = DecompositionReport(
        dimensions=[
            DecomposedDimension(
                key="commitment", name="Commitment",
                definition="willingness to do shared work",
                high_end="high", low_end="low",
                source_keys=["commitment_a", "commitment_b"],
                decision="merged",
            ),
        ],
    )
    out = to_pool_report(settled, reports)
    dim = out.dimensions[0]
    # The primary source's real why is carried forward — NOT an empty/decomposer string.
    assert dim.why_it_differentiates == "Applicants range from eager volunteers to vague."


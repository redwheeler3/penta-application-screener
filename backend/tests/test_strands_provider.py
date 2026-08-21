"""Provider-selection tests for Claude Runtime and OpenAI Mantle models."""

from unittest.mock import MagicMock, patch

from app.ai.strands_provider import OPENAI_REASONING_EFFORT, StrandsProvider


def test_claude_uses_bedrock_runtime_model() -> None:
    provider = StrandsProvider(region="us-east-1", max_pool_connections=7)

    with patch("strands.models.BedrockModel") as model_class:
        model = provider._model_for("us.anthropic.claude-haiku-4-5-20251001-v1:0")

    assert model is model_class.return_value
    kwargs = model_class.call_args.kwargs
    assert kwargs["region_name"] == "us-east-1"
    assert kwargs["boto_client_config"].max_pool_connections == 7
    assert kwargs["boto_client_config"].read_timeout == provider.DEFAULT_READ_TIMEOUT


def test_openai_uses_bedrock_mantle_responses_model() -> None:
    provider = StrandsProvider(region="us-east-1")

    with patch("strands.models.openai_responses.OpenAIResponsesModel") as model_class:
        model = provider._model_for("openai.gpt-5.6-luna", read_timeout=321)

    assert model is model_class.return_value
    kwargs = model_class.call_args.kwargs
    assert kwargs["model_id"] == "openai.gpt-5.6-luna"
    assert kwargs["bedrock_mantle_config"] == {"region": "us-east-1"}
    assert kwargs["client_args"]["max_retries"] == 5
    assert kwargs["client_args"]["timeout"].read == 321
    assert OPENAI_REASONING_EFFORT == "low"
    assert kwargs["params"] == {"reasoning": {"effort": "low"}}
    assert kwargs["stateful"] is False


def test_openai_reasoning_effort_can_be_set_for_bakeoff() -> None:
    provider = StrandsProvider(region="us-east-1", openai_reasoning_effort="low")

    with patch("strands.models.openai_responses.OpenAIResponsesModel") as model_class:
        provider._model_for("openai.gpt-5.6-luna")

    assert model_class.call_args.kwargs["params"] == {"reasoning": {"effort": "low"}}


def test_openai_reasoning_effort_can_differ_by_model() -> None:
    provider = StrandsProvider(
        region="us-east-1",
        openai_reasoning_effort="none",
        openai_reasoning_efforts={"openai.gpt-5.6-luna": "low"},
    )

    with patch("strands.models.openai_responses.OpenAIResponsesModel") as model_class:
        provider._model_for("openai.gpt-5.6-luna")
        provider._model_for("openai.gpt-5.6-terra")

    assert model_class.call_args_list[0].kwargs["params"] == {"reasoning": {"effort": "low"}}
    assert model_class.call_args_list[1].kwargs["params"] == {"reasoning": {"effort": "none"}}


def test_models_are_cached_by_model_and_timeout() -> None:
    provider = StrandsProvider(region="us-east-1")
    built = MagicMock(side_effect=[MagicMock(), MagicMock(), MagicMock()])

    with patch.object(provider, "_build_model", built):
        first = provider._model_for("openai.gpt-5.6-luna")
        same = provider._model_for("openai.gpt-5.6-luna")
        longer = provider._model_for("openai.gpt-5.6-luna", read_timeout=300)
        other = provider._model_for("openai.gpt-5.6-terra")

    assert same is first
    assert longer is not first
    assert other is not first
    assert built.call_count == 3

"""Tests for `src.pipeline.steps`: the `CallableStep` and `MapStep` generic adapters."""

import pytest
from src.core.exceptions import NotFoundError, ValidationError
from src.pipeline.context import PipelineContext
from src.pipeline.steps import CallableStep, MapStep


class TestCallableStep:
    """Tests for `CallableStep`."""

    @pytest.mark.asyncio
    async def test_calls_sync_func_with_no_inputs_and_stores_result(self) -> None:
        step = CallableStep("greet", lambda: "hello", output_key="greeting")
        context = await step.execute(PipelineContext())
        assert context.get("greeting") == "hello"

    @pytest.mark.asyncio
    async def test_calls_sync_func_with_inputs_in_order(self) -> None:
        step = CallableStep(
            "subtract",
            lambda a, b: a - b,
            input_keys=("minuend", "subtrahend"),
            output_key="difference",
        )
        context = PipelineContext(values={"minuend": 10, "subtrahend": 3})
        result = await step.execute(context)
        assert result.get("difference") == 7

    @pytest.mark.asyncio
    async def test_calls_async_func_and_awaits_it(self) -> None:
        async def double(value: int) -> int:
            return value * 2

        step = CallableStep(
            "double", double, input_keys=("value",), output_key="doubled", is_async=True
        )
        context = PipelineContext(values={"value": 21})
        result = await step.execute(context)
        assert result.get("doubled") == 42

    @pytest.mark.asyncio
    async def test_missing_input_key_raises_not_found(self) -> None:
        step = CallableStep("greet", lambda name: name, input_keys=("name",), output_key="out")
        with pytest.raises(NotFoundError):
            await step.execute(PipelineContext())

    @pytest.mark.asyncio
    async def test_underlying_exception_propagates_unwrapped(self) -> None:
        def boom() -> None:
            raise ValueError("bad input")

        step = CallableStep("boom", boom, output_key="out")
        with pytest.raises(ValueError, match="bad input"):
            await step.execute(PipelineContext())

    def test_name_property_matches_constructor_argument(self) -> None:
        step = CallableStep("greet", lambda: None, output_key="out")
        assert step.name == "greet"

    def test_rejects_blank_name(self) -> None:
        with pytest.raises(ValidationError):
            CallableStep("  ", lambda: None, output_key="out")

    def test_rejects_blank_output_key(self) -> None:
        with pytest.raises(ValidationError):
            CallableStep("greet", lambda: None, output_key="  ")

    @pytest.mark.asyncio
    async def test_overwrites_output_key_if_already_present(self) -> None:
        step = CallableStep("greet", lambda: "new", output_key="greeting")
        context = PipelineContext(values={"greeting": "old"})
        result = await step.execute(context)
        assert result.get("greeting") == "new"


class TestMapStep:
    """Tests for `MapStep`."""

    @pytest.mark.asyncio
    async def test_applies_sync_func_to_every_item_in_order(self) -> None:
        step = MapStep("square", lambda x: x * x, input_key="numbers", output_key="squares")
        context = PipelineContext(values={"numbers": [1, 2, 3, 4]})
        result = await step.execute(context)
        assert result.get("squares") == (1, 4, 9, 16)

    @pytest.mark.asyncio
    async def test_applies_async_func_to_every_item_in_order(self) -> None:
        async def double(value: int) -> int:
            return value * 2

        step = MapStep(
            "double", double, input_key="numbers", output_key="doubled", is_async=True
        )
        context = PipelineContext(values={"numbers": [1, 2, 3]})
        result = await step.execute(context)
        assert result.get("doubled") == (2, 4, 6)

    @pytest.mark.asyncio
    async def test_empty_input_sequence_produces_empty_output(self) -> None:
        step = MapStep("square", lambda x: x * x, input_key="numbers", output_key="squares")
        context = PipelineContext(values={"numbers": []})
        result = await step.execute(context)
        assert result.get("squares") == ()

    @pytest.mark.asyncio
    async def test_preserves_input_order_even_when_func_output_is_unordered_looking(self) -> None:
        calls: list[int] = []

        def record(value: int) -> int:
            calls.append(value)
            return value

        step = MapStep("record", record, input_key="numbers", output_key="recorded")
        context = PipelineContext(values={"numbers": [5, 3, 9, 1]})
        result = await step.execute(context)
        assert calls == [5, 3, 9, 1]
        assert result.get("recorded") == (5, 3, 9, 1)

    @pytest.mark.asyncio
    async def test_missing_input_key_raises_not_found(self) -> None:
        step = MapStep("square", lambda x: x * x, input_key="numbers", output_key="squares")
        with pytest.raises(NotFoundError):
            await step.execute(PipelineContext())

    @pytest.mark.asyncio
    async def test_stops_at_first_failing_item(self) -> None:
        def fail_on_three(value: int) -> int:
            if value == 3:
                raise ValueError("cannot process 3")
            return value

        seen: list[int] = []

        def tracking(value: int) -> int:
            seen.append(value)
            return fail_on_three(value)

        step = MapStep("track", tracking, input_key="numbers", output_key="out")
        context = PipelineContext(values={"numbers": [1, 2, 3, 4]})
        with pytest.raises(ValueError, match="cannot process 3"):
            await step.execute(context)
        assert seen == [1, 2, 3]

    def test_rejects_blank_name(self) -> None:
        with pytest.raises(ValidationError):
            MapStep("  ", lambda x: x, input_key="numbers", output_key="squares")

    def test_rejects_blank_input_key(self) -> None:
        with pytest.raises(ValidationError):
            MapStep("square", lambda x: x, input_key="  ", output_key="squares")

    def test_rejects_blank_output_key(self) -> None:
        with pytest.raises(ValidationError):
            MapStep("square", lambda x: x, input_key="numbers", output_key="  ")

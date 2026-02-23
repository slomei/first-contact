"""Tests for models.py — model config, pricing, pure functions."""

import models


def test_models_dict_maps_to_valid_ids():
    for shorthand, model_id in models.MODELS.items():
        assert shorthand.startswith("/")
        assert "claude" in model_id


def test_pricing_covers_all_models():
    for model_id in models.MODELS.values():
        assert model_id in models.PRICING, f"Missing pricing for {model_id}"
        prices = models.PRICING[model_id]
        assert "input" in prices
        assert "output" in prices


def test_model_short_names_reverse_lookup():
    for model_id in models.MODELS.values():
        assert model_id in models.MODEL_SHORT_NAMES
        short = models.MODEL_SHORT_NAMES[model_id]
        assert isinstance(short, str)
        assert len(short) > 0


def test_estimate_conversation_tokens_returns_int():
    # With empty history
    original = models.conversation_history[:]
    models.conversation_history = []
    result = models.estimate_conversation_tokens()
    assert isinstance(result, int)
    assert result == 0
    models.conversation_history = original


def test_track_usage_updates_totals():
    # Save originals
    orig_in = models.session_input_tokens
    orig_out = models.session_output_tokens
    orig_cost = models.session_cost

    cost = models.track_usage(100, 50, "claude-sonnet-4-6")

    assert isinstance(cost, float)
    assert cost > 0
    assert models.session_input_tokens == orig_in + 100
    assert models.session_output_tokens == orig_out + 50
    assert models.session_cost > orig_cost

    # Restore
    models.session_input_tokens = orig_in
    models.session_output_tokens = orig_out
    models.session_cost = orig_cost


def test_track_usage_with_cache_tokens():
    """Cache read cost should be less than full input cost."""
    orig_in = models.session_input_tokens
    orig_out = models.session_output_tokens
    orig_cost = models.session_cost
    orig_cc = models.session_cache_creation_tokens
    orig_cr = models.session_cache_read_tokens

    # Full input cost
    full_cost = models.track_usage(0, 0, "claude-sonnet-4-6",
                                   cache_creation_input_tokens=0,
                                   cache_read_input_tokens=0)

    # Reset
    models.session_input_tokens = orig_in
    models.session_output_tokens = orig_out
    models.session_cost = orig_cost
    models.session_cache_creation_tokens = orig_cc
    models.session_cache_read_tokens = orig_cr

    # Cache read cost for 1000 tokens should be much less than input cost for 1000 tokens
    cache_cost = models.track_usage(0, 0, "claude-sonnet-4-6",
                                    cache_read_input_tokens=1000)
    input_cost = models.track_usage(1000, 0, "claude-sonnet-4-6")

    assert cache_cost < input_cost
    assert models.session_cache_read_tokens == orig_cr + 1000

    # Restore
    models.session_input_tokens = orig_in
    models.session_output_tokens = orig_out
    models.session_cost = orig_cost
    models.session_cache_creation_tokens = orig_cc
    models.session_cache_read_tokens = orig_cr


def test_track_usage_backward_compatible():
    """Old 3-arg calls should still work."""
    orig_in = models.session_input_tokens
    orig_out = models.session_output_tokens
    orig_cost = models.session_cost

    cost = models.track_usage(100, 50, "claude-sonnet-4-6")
    assert isinstance(cost, float)
    assert cost > 0

    # Restore
    models.session_input_tokens = orig_in
    models.session_output_tokens = orig_out
    models.session_cost = orig_cost


def test_track_usage_batch_discount():
    """Batch discount should halve the cost."""
    orig_in = models.session_input_tokens
    orig_out = models.session_output_tokens
    orig_cost = models.session_cost
    orig_cc = models.session_cache_creation_tokens
    orig_cr = models.session_cache_read_tokens

    normal_cost = models.track_usage(1000, 500, "claude-haiku-4-5")

    # Restore
    models.session_input_tokens = orig_in
    models.session_output_tokens = orig_out
    models.session_cost = orig_cost
    models.session_cache_creation_tokens = orig_cc
    models.session_cache_read_tokens = orig_cr

    batch_cost = models.track_usage(1000, 500, "claude-haiku-4-5", batch_discount=True)

    assert abs(batch_cost - normal_cost * 0.5) < 1e-10

    # Restore
    models.session_input_tokens = orig_in
    models.session_output_tokens = orig_out
    models.session_cost = orig_cost
    models.session_cache_creation_tokens = orig_cc
    models.session_cache_read_tokens = orig_cr

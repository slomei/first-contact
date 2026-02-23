"""Tests for batch_api.py — module structure and function signatures."""

import batch_api


def test_batch_api_imports():
    """Module loads and has all expected functions."""
    assert callable(batch_api.submit_batch)
    assert callable(batch_api.poll_until_done)
    assert callable(batch_api.retrieve_results)

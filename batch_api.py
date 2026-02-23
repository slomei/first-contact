"""
Batch API wrapper for Anthropic's Messages Batches endpoint.

Provides submit, poll, and retrieve functions for batch processing.
Used by job_scanner.py for fit assessments at 50% cost.
"""

import time


def submit_batch(requests, client=None):
    """Submit a batch of message requests.

    requests: list of dicts, each with:
        - custom_id: unique string identifier
        - model: model ID string
        - max_tokens: int
        - messages: list of message dicts
        - system: optional system prompt string

    Returns the batch object from the API.
    """
    if client is None:
        import models
        client = models.get_client()

    api_requests = []
    for req in requests:
        params = {
            "model": req["model"],
            "max_tokens": req["max_tokens"],
            "messages": req["messages"],
        }
        if req.get("system"):
            params["system"] = req["system"]

        api_requests.append({
            "custom_id": req["custom_id"],
            "params": params,
        })

    return client.messages.batches.create(requests=api_requests)


def poll_until_done(batch_id, client=None, poll_interval=30, timeout=7200):
    """Poll a batch until processing completes.

    Returns the final batch object.
    Raises TimeoutError if timeout (seconds) is exceeded.
    """
    if client is None:
        import models
        client = models.get_client()

    elapsed = 0
    while elapsed < timeout:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return batch
        time.sleep(poll_interval)
        elapsed += poll_interval

    raise TimeoutError(f"Batch {batch_id} did not complete within {timeout}s")


def retrieve_results(batch_id, client=None):
    """Retrieve results from a completed batch.

    Returns dict mapping custom_id -> result entry.
    Each entry has 'result' with 'type' and 'message' (on success).
    """
    if client is None:
        import models
        client = models.get_client()

    results = {}
    for entry in client.messages.batches.results(batch_id):
        results[entry.custom_id] = entry
    return results

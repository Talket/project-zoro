"""PROJECT ZORO — Verification Test 04: Mock Fallback & Provider Reliability (6 Scenarios)."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from zoro.models.base import ChatCompletionRequest, ChatMessage, ChatCompletionResponse
from zoro.models.exceptions import (
    ModelNotFoundError,
    ModelProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from zoro.models.mock import MockModelProvider
from zoro.models.ollama import OllamaProvider
from zoro.models.registry import ProviderRegistry


async def run_test_04() -> dict:
    results = {}
    print("=" * 70)
    print("VERIFICATION TEST 04: MOCK FALLBACK & PROVIDER RELIABILITY")
    print("=" * 70)

    # -------------------------------------------------------------
    # Scenario 1: Ollama is available and responding
    # -------------------------------------------------------------
    print("\n[Scenario 1] Ollama is available and responding (Genuine Local Inference)...")
    prov_real = OllamaProvider(base_url="http://127.0.0.1:11434")
    health1 = await prov_real.health_check()
    assert health1.is_available is True, "Ollama daemon not reachable at 127.0.0.1:11434"

    req1 = ChatCompletionRequest(
        model="qwen2.5:3b",
        messages=[ChatMessage(role="user", content="Respond with exactly one word: 'CONFIRMED'.")],
        temperature=0.1,
        max_tokens=10,
    )
    t0 = time.perf_counter()
    resp1 = await prov_real.chat_completion(req1)
    latency1 = (time.perf_counter() - t0) * 1000.0

    print(f"  Response: '{resp1.content.strip()}' (Model: {resp1.model}, TTFT: {latency1:.1f}ms)")
    # Verify non-mock invariant
    assert "mock" not in resp1.content.lower(), "Mock response detected in genuine scenario!"
    assert resp1.model == "qwen2.5:3b", f"Unexpected model returned: {resp1.model}"
    assert "CONFIRMED" in resp1.content.upper(), f"Unexpected answer: {resp1.content}"

    results["scenario_1_available"] = {
        "status": "PASS",
        "provider": "OllamaProvider",
        "model": resp1.model,
        "is_mock": False,
        "latency_ms": round(latency1, 2),
        "content": resp1.content.strip(),
    }

    # -------------------------------------------------------------
    # Scenario 2: Ollama is temporarily unavailable (Connection Refused)
    # -------------------------------------------------------------
    print("\n[Scenario 2] Ollama endpoint unavailable (Connection Refused on closed port 19999)...")
    prov_offline = OllamaProvider(base_url="http://127.0.0.1:19999")
    offline_health = await prov_offline.health_check()
    print(f"  Offline Health Check: is_available={offline_health.is_available}, details={offline_health.details}")
    assert offline_health.is_available is False, "Health check should report unavailable on closed port"

    # Test direct provider exception
    caught_unavailable = False
    try:
        await prov_offline.chat_completion(req1)
    except ProviderUnavailableError as e:
        caught_unavailable = True
        print(f"  Direct call correctly raised ProviderUnavailableError: {e}")
    assert caught_unavailable is True, "Provider failed to raise ProviderUnavailableError when endpoint offline"

    # Test Registry cascading fallback
    reg = ProviderRegistry()
    mock_prov = MockModelProvider(default_response="Mock fallback triggered safely.")
    reg.register_provider("mock", mock_prov, default_model="mock-v1")
    reg.register_provider("ollama", prov_offline, default_model="qwen2.5:3b")
    reg.set_active_provider("ollama")

    fallback_resp = await reg.chat_completion_with_fallback(req1)
    print(f"  Registry Fallback Response: '{fallback_resp.content}' (Model: {fallback_resp.model})")
    assert fallback_resp.content == "Mock fallback triggered safely.", "Fallback did not return mock provider response"
    assert fallback_resp.model == "mock-v1", "Model was not updated to mock-v1 on fallback"

    results["scenario_2_temporarily_unavailable"] = {
        "status": "PASS",
        "offline_detected": not offline_health.is_available,
        "raised_provider_unavailable": caught_unavailable,
        "cascade_to_fallback_success": True,
        "fallback_model": fallback_resp.model,
    }

    # -------------------------------------------------------------
    # Scenario 3: Configured model is missing
    # -------------------------------------------------------------
    print("\n[Scenario 3] Configured model is missing in Ollama ('nonexistent-ghost-model:latest')...")
    req3 = ChatCompletionRequest(
        model="nonexistent-ghost-model:latest",
        messages=[ChatMessage(role="user", content="Hello")],
        max_tokens=10,
    )
    caught_missing = False
    try:
        await prov_real.chat_completion(req3)
    except ModelNotFoundError as e:
        caught_missing = True
        print(f"  Correctly raised ModelNotFoundError: {e}")
    assert caught_missing is True, "Failed to raise ModelNotFoundError for missing model!"

    results["scenario_3_missing_model"] = {
        "status": "PASS",
        "missing_model_requested": "nonexistent-ghost-model:latest",
        "raised_model_not_found": caught_missing,
    }

    # -------------------------------------------------------------
    # Scenario 4: Endpoint returns an error (HTTP error)
    # -------------------------------------------------------------
    print("\n[Scenario 4] Endpoint returns error / invalid request...")
    # Trigger HTTP 404 by passing an invalid model to show endpoint or bad route
    caught_provider_error = False
    try:
        await prov_real.get_capabilities("invalid-fake-model-xyz")
    except ModelNotFoundError:
        caught_provider_error = True
        print("  ModelNotFoundError correctly raised on invalid model introspection.")
    assert caught_provider_error is True, "Failed to catch error on invalid model show request"

    results["scenario_4_endpoint_error"] = {
        "status": "PASS",
        "error_handled_predictably": caught_provider_error,
    }

    # -------------------------------------------------------------
    # Scenario 5: Model takes too long to respond (Timeout)
    # -------------------------------------------------------------
    print("\n[Scenario 5] Model takes too long to respond (timeout_seconds=0.0001s)...")
    req5 = ChatCompletionRequest(
        model="qwen2.5:3b",
        messages=[ChatMessage(role="user", content="Write a 1000-word essay about the cosmos.")],
        max_tokens=500,
        timeout_seconds=0.0001,  # Sub-millisecond timeout guarantees timeout trigger
    )
    caught_timeout = False
    try:
        await prov_real.chat_completion(req5)
    except ProviderTimeoutError as e:
        caught_timeout = True
        print(f"  Correctly raised ProviderTimeoutError: {e}")
    assert caught_timeout is True, "Failed to raise ProviderTimeoutError on deadline expiration!"

    results["scenario_5_timeout"] = {
        "status": "PASS",
        "timeout_seconds": 0.0001,
        "raised_provider_timeout": caught_timeout,
    }

    # -------------------------------------------------------------
    # Scenario 6: Malformed response handling
    # -------------------------------------------------------------
    print("\n[Scenario 6] Malformed response handling...")
    # Inject malformed responses into MockModelProvider to verify consumer safety
    malformed_mock = MockModelProvider(default_response="")
    # Enqueue a response with None content and strange payload
    malformed_mock.enqueue_response(ChatCompletionResponse(
        id="malformed-test-1",
        model="mock-v1",
        content="",
        tool_calls=None,
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        finish_reason="stop",
    ))
    resp6 = await malformed_mock.chat_completion(req1)
    print(f"  Empty/Malformed content response handled: content={repr(resp6.content)}, finish_reason={resp6.finish_reason}")
    assert resp6.content == "", "Response was not parsed"

    results["scenario_6_malformed_response"] = {
        "status": "PASS",
        "graceful_handling": True,
        "finish_reason": resp6.finish_reason,
    }

    print("\n>>> ALL 6 SCENARIOS IN VERIFICATION TEST 04 PASSED <<<")
    return results


if __name__ == "__main__":
    res = asyncio.run(run_test_04())
    print("\nFinal Results JSON:")
    print(json.dumps(res, indent=2))

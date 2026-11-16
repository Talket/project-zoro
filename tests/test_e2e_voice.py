"""End-to-End and Engine RPC Integration Tests for ZORO Voice Subsystem."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from zoro.config.settings import ZoroSettings
from zoro.core.engine import ZoroEngine


@pytest.fixture
async def direct_voice_engine(tmp_path: Path):
    settings = ZoroSettings(
        data_dir=tmp_path,
        pipe_name=rf"\\.\pipe\test-voice-rpc-{tmp_path.name}",
        db_path=tmp_path / "voice_rpc.db",
        security_dir=tmp_path / "sec",
        audit_checkpoint_path=tmp_path / "sec" / "audit.checkpoint",
        halt_lock_path=tmp_path / "sec" / "halt.lock",
        pid_path=tmp_path / "sec" / "zoro.pid",
    )
    (tmp_path / "sec").mkdir(parents=True, exist_ok=True)
    engine = ZoroEngine(settings=settings)
    await engine.initialize()
    yield engine, tmp_path
    await engine.shutdown()


@pytest.mark.asyncio
async def test_voice_engine_initialization_and_rpcs(direct_voice_engine):
    """Verify ZoroEngine voice manager initialization and all voice RPC handlers."""
    engine, tmp_path = direct_voice_engine

    assert engine.voice_mgr is not None

    # 1. voice.get_status
    state_res = await engine._rpc_voice_get_status({})
    assert "state" in state_res
    assert "is_enabled" in state_res
    assert "stt_provider" in state_res

    # 2. voice.enable
    start_res = await engine._rpc_voice_enable({})
    assert start_res["success"] is True

    # 3. voice.start_push_to_talk
    ptt_res = await engine._rpc_voice_start_push_to_talk({})
    assert ptt_res["success"] is True

    # 4. voice.stop_push_to_talk
    stop_ptt_res = await engine._rpc_voice_stop_push_to_talk({})
    assert stop_ptt_res["success"] is True

    # 5. voice.stop_speaking
    stop_spk_res = await engine._rpc_voice_stop_speaking({})
    assert stop_spk_res["success"] is True

    # 6. voice.start_listening / stop_listening
    stop_listen_res = await engine._rpc_voice_stop_listening({})
    assert stop_listen_res["success"] is True
    assert stop_listen_res["is_listening"] is False

    start_listen_res = await engine._rpc_voice_start_listening({})
    assert start_listen_res["success"] is True
    assert start_listen_res["is_listening"] is True

    # 7. voice.set_wake_word
    cfg_phrase_res = await engine._rpc_voice_set_wake_word({"phrase": "zoro", "enabled": True})
    assert cfg_phrase_res["success"] is True
    assert "zoro" in cfg_phrase_res["enabled_wake_phrases"]

    # 8. voice.get_devices
    devs_res = await engine._rpc_voice_get_devices({})
    assert "input_devices" in devs_res
    assert "output_devices" in devs_res

    # 9. voice.set_input_device
    in_res = await engine._rpc_voice_set_input_device({"device_index": 0})
    assert in_res["success"] is True

    # 10. voice.set_output_device
    out_res = await engine._rpc_voice_set_output_device({"device_index": 0})
    assert out_res["success"] is True

    # 11. voice.get_providers
    provs_res = await engine._rpc_voice_get_providers({})
    assert "stt_providers" in provs_res
    assert "tts_providers" in provs_res

    # 12. voice.set_stt_provider
    stt_res = await engine._rpc_voice_set_stt_provider({"provider": "mock"})
    assert stt_res["success"] is True
    assert stt_res["active_stt"] == "mock"

    # 13. voice.set_tts_provider
    tts_res = await engine._rpc_voice_set_tts_provider({"provider": "mock"})
    assert tts_res["success"] is True
    assert tts_res["active_tts"] == "mock"

    # 14. voice.get_metrics
    metrics_res = await engine._rpc_voice_get_metrics({})
    assert "summary" in metrics_res
    assert "current" in metrics_res

    # 15. voice.clear_history
    clear_res = await engine._rpc_voice_clear_history({})
    assert clear_res["success"] is True
    assert clear_res["cleared"] >= 1

    # 16. Test convenient alias handlers
    alias_listen = await engine._rpc_voice_set_wake_listening_alias({"enabled": False})
    assert alias_listen["success"] is True
    assert alias_listen["is_listening"] is False

    # 17. voice.disable
    disable_res = await engine._rpc_voice_disable({})
    assert disable_res["success"] is True

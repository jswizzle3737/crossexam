"""Tests for the SessionManager — gateway is wired to accept test credentials."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.orchestrator.session_manager import SessionManager


@pytest.fixture
def mock_gateway():
    with patch("backend.orchestrator.session_manager.WebRTCGateway") as cls:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        cls.return_value = instance
        yield cls


@pytest.mark.asyncio
async def test_session_manager_init(mock_gateway):
    """SessionManager initialises with empty sessions dict."""
    mgr = SessionManager(
        gateway_api_key="test-key",
        gateway_api_secret="test-secret",
    )
    assert mgr._sessions == {}
    await mgr.cleanup()


@pytest.mark.asyncio
async def test_session_manager_forwards_creds(mock_gateway):
    """Credentials passed to SessionManager reach WebRTCGateway."""
    SessionManager(
        gateway_host="my-host",
        gateway_port=7881,
        gateway_api_key="my-key",
        gateway_api_secret="my-secret",
    )
    mock_gateway.assert_called_once_with(
        host="my-host",
        port=7881,
        api_key="my-key",
        api_secret="my-secret",
    )


@pytest.mark.asyncio
async def test_cleanup_closes_gateway(mock_gateway):
    """SessionManager.cleanup() calls gateway.__aexit__()."""
    mgr = SessionManager(gateway_api_key="k", gateway_api_secret="s")
    await mgr.cleanup()
    mgr._gateway.__aexit__.assert_awaited_once()
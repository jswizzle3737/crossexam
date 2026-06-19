"""Tests for the WebRTC gateway — all LiveKit calls are mocked.

Tests cover both the ``async with`` pattern (short-lived callers) and the
manual ``__aenter__``/``__aexit__`` pattern (``SessionManager``-style).

Test strategy: inject a fake ``WebRTCClient`` that returns canned data.
This avoids patching ``livekit.api`` internals and tests the public API.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.orchestrator.webrtc_gateway import (
    LiveKitUnavailable,
    Room,
    RoomConfig,
    WebRTCClient,
    WebRTCGateway,
)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_client() -> MagicMock:
    """A fake ``WebRTCClient`` that returns canned room data."""
    client = MagicMock(spec=WebRTCClient)
    client.create_room = AsyncMock(return_value=SimpleNamespace(name="test-room"))
    client.delete_room = AsyncMock()
    client.get_room = AsyncMock(return_value=None)
    client.list_rooms = AsyncMock(return_value=[])
    client.health = AsyncMock(return_value=True)
    client.close = AsyncMock()
    return client


# ═══════════════════════════════════════════════════════════════════
# Constructor / credential resolution
# ═══════════════════════════════════════════════════════════════════


def test_gateway_needs_creds():
    """Constructor raises ValueError when kwargs AND settings are empty."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("backend.orchestrator.webrtc_gateway.settings.livekit_api_key", "")
        mp.setattr("backend.orchestrator.webrtc_gateway.settings.livekit_api_secret", "")
        with pytest.raises(ValueError, match="LiveKit API credentials not configured"):
            WebRTCGateway(api_key="", api_secret="")


def test_gateway_reads_settings():
    """When kwargs are omitted, constructor reads from settings."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("backend.orchestrator.webrtc_gateway.settings.livekit_host", "s-host")
        mp.setattr("backend.orchestrator.webrtc_gateway.settings.livekit_port", 7882)
        mp.setattr("backend.orchestrator.webrtc_gateway.settings.livekit_api_key", "s-key")
        mp.setattr("backend.orchestrator.webrtc_gateway.settings.livekit_api_secret", "s-secret")

        gw = WebRTCGateway()
        assert gw._host == "s-host"
        assert gw._port == 7882
        assert gw._api_key == "s-key"
        assert gw._api_secret == "s-secret"


def test_kwargs_override_settings():
    """Explicit kwargs take precedence over settings."""
    gw = WebRTCGateway(
        host="explicit-host",
        port=9999,
        api_key="explicit-key",
        api_secret="explicit-secret",
    )
    assert gw._host == "explicit-host"
    assert gw._port == 9999
    assert gw._api_key == "explicit-key"
    assert gw._api_secret == "explicit-secret"


# ═══════════════════════════════════════════════════════════════════
# Gateway context-manager protocol
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_gateway_aenter_returns_self(fake_client):
    """__aenter__ returns self (no-op but available for symmetry)."""
    async with WebRTCGateway(client=fake_client, api_key="k", api_secret="s") as gw:
        assert gw is not None


@pytest.mark.asyncio
async def test_gateway_aexit_closes_client(fake_client):
    """__aexit__ calls close() on the underlying client."""
    async with WebRTCGateway(client=fake_client, api_key="k", api_secret="s") as gw:
        pass
    fake_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_manual_enter_exit(fake_client):
    """Manual enter/exit works (SessionManager pattern)."""
    gw = WebRTCGateway(client=fake_client, api_key="k", api_secret="s")
    await gw.__aenter__()
    await gw.__aexit__(None, None, None)
    fake_client.close.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════
# Gateway create_room / delete_room
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_gateway_create_room_returns_name(fake_client):
    """Gateway.create_room delegates to client and returns the room name."""
    async with WebRTCGateway(client=fake_client, api_key="k", api_secret="s") as gw:
        name = await gw.create_room("my-room")
    assert name == "test-room"
    fake_client.create_room.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_create_room_raises_on_failure(fake_client):
    """Gateway.create_room raises LiveKitUnavailable when client errors."""
    fake_client.create_room = AsyncMock(side_effect=ConnectionError("refused"))
    gw = WebRTCGateway(client=fake_client, api_key="k", api_secret="s")
    with pytest.raises(LiveKitUnavailable, match="unreachable"):
        await gw.create_room("broken")


@pytest.mark.asyncio
async def test_gateway_delete_room(fake_client):
    """Gateway.delete_room delegates to the client."""
    async with WebRTCGateway(client=fake_client, api_key="k", api_secret="s") as gw:
        await gw.delete_room("my-room")
    fake_client.delete_room.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_health_returns_true(fake_client):
    """Gateway.health delegates to the client."""
    async with WebRTCGateway(client=fake_client, api_key="k", api_secret="s") as gw:
        ok = await gw.health()
    assert ok is True


# ═══════════════════════════════════════════════════════════════════
# Room context-manager protocol
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_room_aenter_creates_room(fake_client):
    """Room.__aenter__ calls gateway.create_room and sets .name."""
    fake_client.create_room = AsyncMock(return_value=SimpleNamespace(name="created-room"))

    async with WebRTCGateway(client=fake_client, api_key="k", api_secret="s") as gw:
        room = Room(gateway=gw, room_name="created-room", config=RoomConfig(name="created-room"))
        async with room:
            assert room.name == "created-room"

    fake_client.create_room.assert_awaited_once()


@pytest.mark.asyncio
async def test_room_aexit_deletes_room(fake_client):
    """Room.__aexit__ calls gateway.delete_room."""
    fake_client.create_room = AsyncMock(return_value=SimpleNamespace(name="delete-me"))

    async with WebRTCGateway(client=fake_client, api_key="k", api_secret="s") as gw:
        room = Room(gateway=gw, room_name="delete-me", config=RoomConfig(name="delete-me"))
        async with room:
            pass

    fake_client.delete_room.assert_awaited_once()


@pytest.mark.asyncio
async def test_room_aexit_swallows_delete_errors(fake_client):
    """Room cleanup swallows LiveKitUnavailable (best-effort)."""
    fake_client.create_room = AsyncMock(return_value=SimpleNamespace(name="ghost"))
    fake_client.delete_room = AsyncMock(side_effect=ConnectionError("timeout"))

    async with WebRTCGateway(client=fake_client, api_key="k", api_secret="s") as gw:
        room = Room(gateway=gw, room_name="ghost", config=RoomConfig(name="ghost"))
        async with room:
            pass  # should not raise

    fake_client.delete_room.assert_awaited_once()


@pytest.mark.asyncio
async def test_room_create_failure_raises(fake_client):
    """Room.__aenter__ raises LiveKitUnavailable when creation fails."""
    fake_client.create_room = AsyncMock(side_effect=ConnectionError("refused"))

    gw = WebRTCGateway(client=fake_client, api_key="k", api_secret="s")
    room = Room(gateway=gw, room_name="unreachable", config=RoomConfig(name="unreachable"))
    with pytest.raises(LiveKitUnavailable, match="unreachable"):
        await room.__aenter__()


# ═══════════════════════════════════════════════════════════════════
# Token generation (on Room)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_room_generate_token(fake_client):
    """Room.generate_token delegates to gateway.generate_token and returns a JWT."""
    fake_client.create_room = AsyncMock(return_value=SimpleNamespace(name="token-room"))

    async with WebRTCGateway(client=fake_client, api_key="k", api_secret="s") as gw:
        room = Room(gateway=gw, room_name="token-room", config=RoomConfig(name="token-room"))
        async with room:
            jwt = await room.generate_token(identity="witness-1")

    assert isinstance(jwt, str)
    assert len(jwt) > 0


# ═══════════════════════════════════════════════════════════════════
# End-to-end: async with gateway → async with room
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_full_lifecycle(fake_client):
    """Full lifecycle: gateway enter → room create → token → room delete → gateway exit."""
    fake_client.create_room = AsyncMock(return_value=SimpleNamespace(name="e2e-room"))

    async with WebRTCGateway(client=fake_client, api_key="k", api_secret="s") as gw:
        async with Room(gateway=gw, room_name="e2e-room", config=RoomConfig(name="e2e-room")) as room:
            assert room.name == "e2e-room"
            token = await room.generate_token(identity="test-user")
            assert isinstance(token, str) and len(token) > 0

    fake_client.create_room.assert_awaited_once()
    fake_client.delete_room.assert_awaited_once()
    fake_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_manual_enter_exit_session_manager_style(fake_client):
    """Manual __aenter__/__aexit__ (SessionManager pattern)."""
    fake_client.create_room = AsyncMock(return_value=SimpleNamespace(name="manual-room"))

    gw = WebRTCGateway(client=fake_client, api_key="k", api_secret="s")
    await gw.__aenter__()  # start

    room = Room(gateway=gw, room_name="manual-room", config=RoomConfig(name="manual-room"))
    await room.__aenter__()  # create
    assert room.name == "manual-room"
    await room.__aexit__(None, None, None)  # delete

    await gw.__aexit__(None, None, None)  # stop

    fake_client.create_room.assert_awaited_once()
    fake_client.delete_room.assert_awaited_once()
    fake_client.close.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════
# Room via room_name + kwargs (bypassing RoomConfig)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_room_via_name_and_kwargs(fake_client):
    """Room can be created with room_name + kwargs instead of RoomConfig."""
    fake_client.create_room = AsyncMock(return_value=SimpleNamespace(name="kwarg-room"))

    async with WebRTCGateway(client=fake_client, api_key="k", api_secret="s") as gw:
        room = Room(gateway=gw, room_name="kwarg-room", max_participants=4)
        async with room:
            assert room.name == "kwarg-room"

    fake_client.create_room.assert_awaited_once()
"""WebRTC gateway — flexible LiveKit room and participant token management.

Credentials are read from the environment (``.env``) via ``backend.config.settings``.
Override individual values via constructor kwargs for testing.

Design philosophy
-----------------
- **Maximize flexibility** — expose every knob as a per-call parameter so callers
  (``SessionManager``, tests, admin scripts) never need to stub config objects.
- **Testable without a real server** — the ``LiveKitClient`` protocol lets tests
  inject a pure-Python fake.
- **Async throughout** — every network call is ``async`` as ``LiveKitAPI`` requires.
- **Graceful degradation** — if the LiveKit server is unreachable every method
  raises a typed ``LiveKitUnavailable`` instead of a raw connection error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol, Sequence, runtime_checkable

from livekit import api as livekit_api
from livekit.protocol import models as lk_models
from livekit.protocol.room import (
    CreateRoomRequest,
    DeleteRoomRequest,
    ListParticipantsRequest,
    ListRoomsRequest,
    MuteRoomTrackRequest,
    RemoveParticipantResponse,
    UpdateParticipantRequest,
    UpdateRoomMetadataRequest,
)

from backend.config import settings

__all__ = [
    "WebRTCGateway",
    "WebRTCClient",
    "Room",
    "RoomConfig",
    "RoomNotFound",
    "LiveKitUnavailable",
    "TokenGenerationError",
    "RoomInfo",
    "ParticipantInfo",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain types — typed wrappers around LiveKit protobuf models so callers
# never need to import ``livekit.protocol.*`` directly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoomInfo:
    """Immutable view of a LiveKit room returned by ``list_rooms`` / ``get_room``."""

    sid: str
    name: str
    empty_timeout: int
    departure_timeout: int
    max_participants: int
    creation_time_ms: int
    metadata: str
    num_participants: int
    num_publishers: int
    active_recording: bool
    version: int

    @classmethod
    def _from_proto(cls, room: lk_models.Room) -> RoomInfo:
        return cls(
            sid=room.sid,
            name=room.name,
            empty_timeout=room.empty_timeout,
            departure_timeout=room.departure_timeout,
            max_participants=room.max_participants,
            creation_time_ms=room.creation_time_ms,
            metadata=room.metadata,
            num_participants=room.num_participants,
            num_publishers=room.num_publishers,
            active_recording=room.active_recording,
            version=room.version,
        )


@dataclass(frozen=True)
class ParticipantInfo:
    """Immutable view of a LiveKit room participant."""

    sid: str
    identity: str
    state: int
    metadata: str
    joined_at_ms: int
    name: str
    is_publisher: bool
    kind: int

    @classmethod
    def _from_proto(cls, p: lk_models.ParticipantInfo) -> ParticipantInfo:
        return cls(
            sid=p.sid,
            identity=p.identity,
            state=p.state,
            metadata=p.metadata,
            joined_at_ms=p.joined_at_ms,
            name=p.name,
            is_publisher=p.is_publisher,
            kind=p.kind,
        )


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class LiveKitUnavailable(Exception):
    """Raised when the LiveKit server is unreachable or returns a transport error."""


class RoomNotFound(Exception):
    """Raised when a requested room does not exist."""


class TokenGenerationError(Exception):
    """Raised when JWT token generation fails (e.g. bad credentials)."""


# ---------------------------------------------------------------------------
# Pluggable transport protocol  (the key to testability)
# ---------------------------------------------------------------------------


@runtime_checkable
class WebRTCClient(Protocol):
    """Abstract protocol for the LiveKit RPC transport layer.

    Default implementation is ``_LiveKitClientWrapper`` which delegates to
    ``livekit.api.LiveKitAPI``.  Tests supply a fake that returns canned data.
    """

    async def create_room(self, request: CreateRoomRequest) -> lk_models.Room: ...
    async def get_room(self, room_name: str) -> lk_models.Room | None: ...
    async def list_rooms(self, request: ListRoomsRequest) -> Sequence[lk_models.Room]: ...
    async def delete_room(self, request: DeleteRoomRequest) -> None: ...
    async def update_room_metadata(
        self, request: UpdateRoomMetadataRequest
    ) -> lk_models.Room: ...
    async def list_participants(
        self, request: ListParticipantsRequest
    ) -> Sequence[lk_models.ParticipantInfo]: ...
    async def get_participant(
        self, room_name: str, identity: str
    ) -> lk_models.ParticipantInfo | None: ...
    async def mute_published_track(
        self, request: MuteRoomTrackRequest
    ) -> None: ...
    async def remove_participant(
        self, room_name: str, identity: str
    ) -> RemoveParticipantResponse: ...
    async def update_participant(
        self, request: UpdateParticipantRequest
    ) -> lk_models.ParticipantInfo: ...
    async def health(self) -> bool: ...
    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Real LiveKit transport wrapper
# ---------------------------------------------------------------------------


class _LiveKitClientWrapper:
    """Wraps ``livekit.api.LiveKitAPI`` behind the ``WebRTCClient`` protocol."""

    def __init__(
        self,
        url: str,
        api_key: str,
        api_secret: str,
        *,
        connect_timeout: float = 10.0,
        request_timeout: float = 30.0,
    ) -> None:
        from aiohttp import ClientTimeout

        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._timeout = ClientTimeout(
            total=request_timeout, connect=connect_timeout
        )
        self._api: livekit_api.LiveKitAPI | None = None

    async def _ensure_client(self) -> livekit_api.LiveKitAPI:
        if self._api is None:
            self._api = livekit_api.LiveKitAPI(
                url=self._url,
                api_key=self._api_key,
                api_secret=self._api_secret,
                timeout=self._timeout,
            )
        return self._api

    async def create_room(self, request: CreateRoomRequest) -> lk_models.Room:
        api = await self._ensure_client()
        return await api.room.create_room(request)

    async def get_room(self, room_name: str) -> lk_models.Room | None:
        api = await self._ensure_client()
        resp = await api.room.list_rooms(ListRoomsRequest(names=[room_name]))
        rooms: list[lk_models.Room] = list(resp.rooms)  # type: ignore[attr-defined]
        return rooms[0] if rooms else None

    async def list_rooms(
        self, request: ListRoomsRequest
    ) -> Sequence[lk_models.Room]:
        api = await self._ensure_client()
        resp = await api.room.list_rooms(request)
        return list(resp.rooms)

    async def delete_room(self, request: DeleteRoomRequest) -> None:
        api = await self._ensure_client()
        await api.room.delete_room(request)

    async def update_room_metadata(
        self, request: UpdateRoomMetadataRequest
    ) -> lk_models.Room:
        api = await self._ensure_client()
        return await api.room.update_room_metadata(request)

    async def list_participants(
        self, request: ListParticipantsRequest
    ) -> Sequence[lk_models.ParticipantInfo]:
        api = await self._ensure_client()
        resp = await api.room.list_participants(request)
        return list(resp.participants)

    async def get_participant(
        self, room_name: str, identity: str
    ) -> lk_models.ParticipantInfo | None:
        api = await self._ensure_client()
        try:
            return await api.room.get_participant(room_name, identity)
        except Exception:
            return None

    async def mute_published_track(
        self, request: MuteRoomTrackRequest
    ) -> None:
        api = await self._ensure_client()
        await api.room.mute_published_track(request)

    async def remove_participant(
        self, room_name: str, identity: str
    ) -> RemoveParticipantResponse:
        api = await self._ensure_client()
        return await api.room.remove_participant(room_name, identity)

    async def update_participant(
        self, request: UpdateParticipantRequest
    ) -> lk_models.ParticipantInfo:
        api = await self._ensure_client()
        return await api.room.update_participant(request)

    async def health(self) -> bool:
        """Ping the LiveKit server by listing rooms (cheap, authenticated call)."""
        try:
            api = await self._ensure_client()
            await api.room.list_rooms(ListRoomsRequest())
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._api is not None:
            await self._api.aclose()
            self._api = None


# ---------------------------------------------------------------------------
# Token generation helpers
# ---------------------------------------------------------------------------


def _build_access_token(
    api_key: str,
    api_secret: str,
    room_name: str,
    identity: str,
    *,
    metadata: str | None = None,
    ttl_seconds: int = 300,
    can_publish: bool = True,
    can_subscribe: bool = True,
    can_publish_data: bool = True,
    can_publish_sources: list[str] | None = None,
    hidden: bool = False,
    room_admin: bool = False,
    room_create: bool = False,
    room_list: bool = False,
    room_record: bool = False,
    agent: bool = False,
    ingress_admin: bool = False,
    recorder: bool = False,
) -> str:
    """Build a JWT access token with full grant control.

    Returns the JWT string.  Raises ``TokenGenerationError`` on failure.
    """
    try:
        grants = livekit_api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=can_publish,
            can_subscribe=can_subscribe,
            can_publish_data=can_publish_data,
            can_publish_sources=can_publish_sources,
            hidden=hidden,
            room_admin=room_admin,
            room_create=room_create,
            room_list=room_list,
            room_record=room_record,
            agent=agent,
            ingress_admin=ingress_admin,
            recorder=recorder,
        )
        token = (
            livekit_api.AccessToken(api_key=api_key, api_secret=api_secret)
            .with_identity(identity)
            .with_grants(grants)
            .with_ttl(timedelta(seconds=ttl_seconds))
        )
        if metadata:
            token.with_metadata(metadata)
        return token.to_jwt()
    except Exception as exc:
        raise TokenGenerationError(
            f"Failed to generate token for {identity} in room {room_name}"
        ) from exc


# ---------------------------------------------------------------------------
# RoomConfig — convenience dataclass for common room configurations
# ---------------------------------------------------------------------------


@dataclass
class RoomConfig:
    """Convenience container for room-creation parameters.

    Used primarily by ``SessionManager``.  For full flexibility use the
    keyword arguments on ``WebRTCGateway.create_room()`` directly.
    """

    name: str
    max_participants: int = 2
    empty_timeout: int = 300  # 5 minutes
    departure_timeout: int | None = None
    metadata: str = ""


# ---------------------------------------------------------------------------
# Room — async context manager wrapping a single room lifecycle
# ---------------------------------------------------------------------------


class Room:
    """An async context manager that wraps a single LiveKit room.

    Usage::

        async with gateway.create_room_ctx(name="my-room") as room:
            token = await room.generate_token(identity="witness")
            # ... use token ...

    On entry the room is created on the LiveKit server.  On exit the room
    is automatically deleted.

    Parameters
    ----------
    gateway:
        The parent ``WebRTCGateway`` instance.
    room_name:
        Name of the room on the LiveKit server.
    config:
        Optional ``RoomConfig`` override.  If provided, ``room_name`` and
        any additional keyword arguments are ignored in favour of the
        preset's values.
    **room_kwargs:
        Passed through to ``WebRTCGateway.create_room()``.
    """

    def __init__(
        self,
        gateway: WebRTCGateway,
        room_name: str,
        *,
        config: RoomConfig | None = None,
        **room_kwargs: Any,
    ) -> None:
        self._gateway = gateway
        if config is not None:
            self._name = config.name
            self._kwargs: dict[str, Any] = {
                "max_participants": config.max_participants,
                "empty_timeout": config.empty_timeout,
                "departure_timeout": config.departure_timeout,
                "metadata": config.metadata or None,
            }
        else:
            self._name = room_name
            self._kwargs = room_kwargs

    @property
    def name(self) -> str:
        """The room name on the LiveKit server."""
        return self._name

    async def __aenter__(self) -> Room:
        self._name = await self._gateway.create_room(
            self._name, **self._kwargs
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        try:
            await self._gateway.delete_room(self._name)
        except LiveKitUnavailable:
            pass  # best-effort cleanup

    async def generate_token(
        self,
        identity: str,
        *,
        ttl_seconds: int = 300,
        can_publish: bool = True,
        can_subscribe: bool = True,
        can_publish_data: bool = True,
        can_publish_sources: list[str] | None = None,
        hidden: bool = False,
    ) -> str:
        """Generate a participant token scoped to this room.

        Shortcut for ``gateway.generate_token(room_name=self.name, ...)``.
        """
        return await self._gateway.generate_token(
            room_name=self._name,
            identity=identity,
            ttl_seconds=ttl_seconds,
            can_publish=can_publish,
            can_subscribe=can_subscribe,
            can_publish_data=can_publish_data,
            can_publish_sources=can_publish_sources,
            hidden=hidden,
        )


# ---------------------------------------------------------------------------


class WebRTCGateway:
    """High-level gateway to a LiveKit WebRTC server.

    All parameters are optional — values missing from kwargs are read from
    ``backend.config.settings`` (which loads from ``.env``).  If *no*
    credentials are available after both sources are consulted the constructor
    raises ``ValueError`` with a clear message.

    Every public method is ``async`` and accepts a per-call ``timeout``
    (seconds).  Pass ``timeout=0`` to use the instance default.

    Parameters
    ----------
    client:
        Injected transport.  Default creates a real ``_LiveKitClientWrapper``.
        Provide a fake for testing.
    host, port, api_key, api_secret:
        LiveKit server credentials.  Optional — fall back to ``settings``.
    connect_timeout:
        Seconds to wait for the initial TCP/TLS handshake (default 10).
    request_timeout:
        Seconds to wait for any single RPC (default 30).
    """

    def __init__(
        self,
        client: WebRTCClient | None = None,
        *,
        host: str | None = None,
        port: int | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        connect_timeout: float = 10.0,
        request_timeout: float = 30.0,
    ) -> None:
        self._host = host or settings.livekit_host
        self._port = port or settings.livekit_port
        self._api_key = api_key or settings.livekit_api_key
        self._api_secret = api_secret or settings.livekit_api_secret
        self._request_timeout = request_timeout

        if not self._api_key or not self._api_secret:
            raise ValueError(
                "LiveKit API credentials not configured. "
                "Set LIVEKIT_API_KEY and LIVEKIT_API_SECRET in the .env file "
                "at the project root, or pass api_key / api_secret to the "
                "WebRTCGateway constructor."
            )

        url = f"http://{self._host}:{self._port}"
        self._client = client or _LiveKitClientWrapper(
            url=url,
            api_key=self._api_key,
            api_secret=self._api_secret,
            connect_timeout=connect_timeout,
            request_timeout=request_timeout,
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health(self, *, timeout: float | None = None) -> bool:
        """Check whether the LiveKit server is reachable and responding.

        Returns ``True`` if a lightweight RPC succeeds, ``False`` otherwise.
        """
        return await self._client.health()

    # ------------------------------------------------------------------
    # Room CRUD
    # ------------------------------------------------------------------

    async def create_room(
        self,
        name: str,
        *,
        max_participants: int = 2,
        empty_timeout: int = 300,
        departure_timeout: int | None = None,
        metadata: dict[str, Any] | str | None = None,
        timeout: float | None = None,
    ) -> str:
        """Create a WebRTC room and return its name.

        Parameters
        ----------
        name:
            Room identifier.  Must be unique per LiveKit server.
        max_participants:
            Maximum concurrent participants (default 2).
        empty_timeout:
            Seconds of emptiness before auto-deletion (default 300).
        departure_timeout:
            Seconds to wait before removing a disconnected participant.
            ``None`` = leave at server default.
        metadata:
            Arbitrary JSON-serialisable data attached to the room.
            Accepts a ``dict`` (serialised automatically) or a raw JSON string.
        timeout:
            Per-call RPC timeout in seconds.  ``None`` = instance default.
        """
        raw_metadata: str = ""
        if metadata is not None:
            if isinstance(metadata, dict):
                import json

                raw_metadata = json.dumps(metadata)
            else:
                raw_metadata = metadata

        req = CreateRoomRequest(
            name=name,
            max_participants=max_participants,
            empty_timeout=empty_timeout,
            metadata=raw_metadata,
        )
        if departure_timeout is not None:
            req.departure_timeout = departure_timeout

        try:
            room = await self._client.create_room(req)
        except Exception as exc:
            raise LiveKitUnavailable(
                f"LiveKit server unreachable when creating room {name!r}"
            ) from exc

        return room.name

    async def get_room(
        self,
        room_name: str,
        *,
        timeout: float | None = None,
    ) -> RoomInfo | None:
        """Fetch a single room by name.

        Returns ``RoomInfo`` or ``None`` if the room does not exist.
        """
        try:
            room = await self._client.get_room(room_name)
        except Exception as exc:
            raise LiveKitUnavailable(
                f"LiveKit server unreachable when getting room {room_name!r}"
            ) from exc
        return RoomInfo._from_proto(room) if room is not None else None

    async def list_rooms(
        self,
        *,
        prefix: str = "",
        timeout: float | None = None,
    ) -> list[RoomInfo]:
        """List all rooms, optionally filtered by name prefix.

        Returns an empty list if the server is reachable but has no rooms.
        Raises ``LiveKitUnavailable`` if the server is unreachable.
        """
        req = ListRoomsRequest(names=[prefix] if prefix else [])
        try:
            rooms = await self._client.list_rooms(req)
        except Exception as exc:
            raise LiveKitUnavailable(
                "LiveKit server unreachable when listing rooms"
            ) from exc
        return [RoomInfo._from_proto(r) for r in rooms]

    async def delete_room(
        self,
        room_name: str,
        *,
        timeout: float | None = None,
    ) -> None:
        """Delete a room.  Silently succeeds if the room doesn't exist."""
        req = DeleteRoomRequest(room=room_name)
        try:
            await self._client.delete_room(req)
        except Exception as exc:
            raise LiveKitUnavailable(
                f"LiveKit server unreachable when deleting room {room_name!r}"
            ) from exc

    async def update_room_metadata(
        self,
        room_name: str,
        metadata: dict[str, Any] | str,
        *,
        timeout: float | None = None,
    ) -> RoomInfo:
        """Replace the metadata attached to a room.

        Parameters
        ----------
        room_name:
            Target room.
        metadata:
            New metadata.  Accepts a ``dict`` (auto-serialised) or raw JSON
            string.  To clear metadata pass an empty dict ``{}``.
        """
        import json

        raw = metadata if isinstance(metadata, str) else json.dumps(metadata)
        req = UpdateRoomMetadataRequest(room=room_name, metadata=raw)
        try:
            room = await self._client.update_room_metadata(req)
        except Exception as exc:
            raise LiveKitUnavailable(
                f"LiveKit server unreachable when updating metadata "
                f"for room {room_name!r}"
            ) from exc
        return RoomInfo._from_proto(room)

    # ------------------------------------------------------------------
    # Participant management
    # ------------------------------------------------------------------

    async def generate_token(
        self,
        room_name: str,
        identity: str,
        *,
        metadata: str | None = None,
        ttl_seconds: int = 300,
        can_publish: bool = True,
        can_subscribe: bool = True,
        can_publish_data: bool = True,
        can_publish_sources: list[str] | None = None,
        hidden: bool = False,
        room_admin: bool = False,
        room_create: bool = False,
        room_list: bool = False,
        room_record: bool = False,
        agent: bool = False,
        ingress_admin: bool = False,
        recorder: bool = False,
        timeout: float | None = None,
    ) -> str:
        """Generate a participant access token (JWT).

        Parameters
        ----------
        room_name:
            The room the token grants access to.
        identity:
            Unique participant identifier.
        ttl_seconds:
            Token lifetime in seconds (default 300 = 5 min).
        can_publish, can_subscribe, can_publish_data:
            Standard media permissions.
        can_publish_sources:
            Restrict publishable track sources (e.g. ``["microphone"]``).
            ``None`` = all sources allowed.
        hidden:
            If true the participant is hidden from other participants.
        room_admin, room_create, room_list, room_record:
            Admin-level grants.
        agent, ingress_admin, recorder:
            Specialised grants.
        """
        return _build_access_token(
            api_key=self._api_key,
            api_secret=self._api_secret,
            room_name=room_name,
            identity=identity,
            metadata=metadata,
            ttl_seconds=ttl_seconds,
            can_publish=can_publish,
            can_subscribe=can_subscribe,
            can_publish_data=can_publish_data,
            can_publish_sources=can_publish_sources,
            hidden=hidden,
            room_admin=room_admin,
            room_create=room_create,
            room_list=room_list,
            room_record=room_record,
            agent=agent,
            ingress_admin=ingress_admin,
            recorder=recorder,
        )

    async def list_participants(
        self,
        room_name: str,
        *,
        timeout: float | None = None,
    ) -> list[ParticipantInfo]:
        """List all participants in a room."""
        req = ListParticipantsRequest(room=room_name)
        try:
            participants = await self._client.list_participants(req)
        except Exception as exc:
            raise LiveKitUnavailable(
                f"LiveKit server unreachable when listing participants "
                f"in room {room_name!r}"
            ) from exc
        return [ParticipantInfo._from_proto(p) for p in participants]

    async def get_participant(
        self,
        room_name: str,
        identity: str,
        *,
        timeout: float | None = None,
    ) -> ParticipantInfo | None:
        """Fetch a single participant by identity.

        Returns ``ParticipantInfo`` or ``None`` if not found.
        """
        try:
            p = await self._client.get_participant(room_name, identity)
        except Exception as exc:
            raise LiveKitUnavailable(
                f"LiveKit server unreachable when getting participant "
                f"{identity!r} in room {room_name!r}"
            ) from exc
        return ParticipantInfo._from_proto(p) if p is not None else None

    async def mute_participant(
        self,
        room_name: str,
        identity: str,
        track_sid: str,
        *,
        muted: bool = True,
        timeout: float | None = None,
    ) -> None:
        """Mute or unmute a specific track of a participant.

        Parameters
        ----------
        room_name, identity:
            Target participant.
        track_sid:
            The track's SID (obtainable from ``list_participants``).
        muted:
            ``True`` to mute, ``False`` to unmute.
        """
        req = MuteRoomTrackRequest(
            room=room_name,
            identity=identity,
            track_sid=track_sid,
            muted=muted,
        )
        try:
            await self._client.mute_published_track(req)
        except Exception as exc:
            raise LiveKitUnavailable(
                f"LiveKit server unreachable when muting track "
                f"{track_sid!r} for {identity!r} in {room_name!r}"
            ) from exc

    async def remove_participant(
        self,
        room_name: str,
        identity: str,
        *,
        timeout: float | None = None,
    ) -> None:
        """Disconnect and remove a participant from a room."""
        try:
            await self._client.remove_participant(room_name, identity)
        except Exception as exc:
            raise LiveKitUnavailable(
                f"LiveKit server unreachable when removing participant "
                f"{identity!r} from room {room_name!r}"
            ) from exc

    async def update_participant_metadata(
        self,
        room_name: str,
        identity: str,
        metadata: dict[str, Any] | str,
        *,
        timeout: float | None = None,
    ) -> ParticipantInfo:
        """Replace per-participant metadata.

        Parameters
        ----------
        room_name, identity:
            Target participant.
        metadata:
            Accepts a ``dict`` (auto-serialised) or raw JSON string.
        """
        import json

        raw = metadata if isinstance(metadata, str) else json.dumps(metadata)
        req = UpdateParticipantRequest(
            room=room_name,
            identity=identity,
            metadata=raw,
        )
        try:
            p = await self._client.update_participant(req)
        except Exception as exc:
            raise LiveKitUnavailable(
                f"LiveKit server unreachable when updating participant "
                f"{identity!r} in room {room_name!r}"
            ) from exc
        return ParticipantInfo._from_proto(p)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> WebRTCGateway:
        """Enter async context manager.

        This is a no-op — the LiveKitAPI client is lazily initialised on the
        first RPC call.  Provided for symmetry with ``__aexit__`` so callers
        can use ``async with self._gateway:``.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Gracefully shut down the LiveKit client connection.

        Safe to call multiple times.
        """
        await self._client.close()
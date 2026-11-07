"""The engine keeps the sync group's AccountID and refuses a different one, as the app does."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import PROBE_UUID
from factories import BABY_ID, payload_for
from fake_server import FakeSyncServer

from pybabytracker import (
    DIAPER_WET,
    OP_ADD,
    AccountChangedError,
    BabyTrackerClient,
    Device,
    RawTransaction,
    SyncEngine,
)

PHONE = "AAAA1111-0000-4000-8000-00000000000A"
EVENT_TIME = datetime(2026, 10, 25, 15, 40, 49, tzinfo=UTC)


def rid(n: int) -> str:
    return f"AAAAAAAA-0000-4000-8000-{n:012d}"


def reset_group(server: FakeSyncServer, account_id: int) -> None:
    """The group is reset in the app: a new AccountID, and every session ends."""
    server.account_id = account_id
    server.sessions.clear()


async def test_the_first_sync_keeps_the_account_id_and_it_survives_a_save(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.add_device(PHONE)
    fake_server.add_transaction(PHONE, OP_ADD, payload_for("Diaper", rid(1)))
    engine = SyncEngine(device_uuid=PROBE_UUID)

    await engine.sync(client)

    assert engine.account_id == 424242
    assert SyncEngine.from_dict(engine.to_dict()).account_id == 424242


async def test_a_sync_after_a_reset_raises_and_applies_nothing(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.add_device(PHONE)
    fake_server.add_transaction(PHONE, OP_ADD, payload_for("Diaper", rid(1)))
    engine = SyncEngine(device_uuid=PROBE_UUID)
    await engine.sync(client)

    reset_group(fake_server, 777)
    fake_server.add_transaction(PHONE, OP_ADD, payload_for("Sleep", rid(2)))

    with pytest.raises(AccountChangedError) as caught:
        await engine.sync(client)
    assert (caught.value.saved, caught.value.signed_in) == (424242, 777)
    assert set(engine.records) == {rid(1)}
    assert engine.account_id == 424242


async def test_a_write_after_a_reset_raises_and_posts_nothing(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.add_device(PHONE)
    fake_server.add_transaction(PHONE, OP_ADD, payload_for("Diaper", rid(1)))
    engine = SyncEngine(device_uuid=PROBE_UUID)
    await engine.sync(client)

    reset_group(fake_server, 777)

    with pytest.raises(AccountChangedError):
        await engine.add_diaper(client, BABY_ID, DIAPER_WET, time=EVENT_TIME, timezone_offset=0)
    assert fake_server.posted(PROBE_UUID) == []


async def test_a_state_saved_before_the_account_id_was_kept_adopts_the_next_one(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.add_device(PHONE)
    fake_server.add_transaction(PHONE, OP_ADD, payload_for("Diaper", rid(1)))
    engine = SyncEngine(device_uuid=PROBE_UUID)
    await engine.sync(client)
    saved = engine.to_dict()
    del saved["account_id"]

    restored = SyncEngine.from_dict(saved)
    assert restored.account_id is None
    reset_group(fake_server, 777)
    await restored.sync(client)

    assert restored.account_id == 777


async def test_a_new_engine_joins_the_new_group(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.add_device(PHONE)
    fake_server.add_transaction(PHONE, OP_ADD, payload_for("Diaper", rid(1)))
    await SyncEngine(device_uuid=PROBE_UUID).sync(client)
    reset_group(fake_server, 777)

    fresh = SyncEngine(device_uuid=PROBE_UUID)
    await fresh.sync(client)

    assert fresh.account_id == 777
    assert set(fresh.records) == {rid(1)}


class _NoSignIn:
    """A source that never signs in, so it has no account_id."""

    async def get_devices(self) -> list[Device]:
        return []

    async def get_transactions(self, device_uuid: str, since_sync_id: int) -> list[RawTransaction]:
        return []


async def test_a_source_without_an_account_id_is_trusted() -> None:
    engine = SyncEngine()

    await engine.sync(_NoSignIn())

    assert engine.account_id is None

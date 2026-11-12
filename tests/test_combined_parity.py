"""Checks that only make sense with every parity branch combined (invented data only)."""

from __future__ import annotations

from typing import Any

import pytest
from factories import BABY_ID, payload_for
from fake_server import FakeSyncServer
from selection_helpers import PHONE, rid, seed, synced

from pybabytracker import (
    OP_CONFLICT,
    BabyTrackerClient,
    EntryInUseError,
    OtherActivity,
    OtherActivityDescription,
)

BATH: dict[str, Any] = {
    "BCObjectType": "OtherActivityDescription",
    "objectID": "92000000-0000-4000-8000-0000000000B1",
    "name": "Bath",
    "newFlage": "true",
    "timestamp": "2026-03-25 03:48:13 +0000",
}
BATH_TWIN: dict[str, Any] = {**BATH, "objectID": "A3000000-0000-4000-8000-0000000000B2"}


def activity_of(kind: dict[str, Any], n: int) -> dict[str, Any]:
    payload = payload_for("OtherActivity", rid(n))
    embedded = {**kind, "newFlage": "false", "timestamp": "1970-01-01 00:00:00 +0000"}
    payload.update(desc=embedded, duration=10)
    return payload


def conflict(winner: dict[str, Any], loser: dict[str, Any]) -> dict[str, Any]:
    return {
        "BCObjectType": "ConflictRecord",
        "objectID": "CF000000-0000-4000-8000-0000000000C2",
        "timestamp": "2026-11-12 10:00:00 +0000",
        "newFlage": True,
        "winner": winner,
        "loser": loser,
    }


async def test_a_conflict_between_two_activity_types_folds_them(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    seed(fake_server, BATH, BATH_TWIN, activity_of(BATH, 3), activity_of(BATH_TWIN, 4))
    fake_server.add_transaction(PHONE, OP_CONFLICT, conflict(BATH, BATH_TWIN))

    engine = await synced(client)

    assert isinstance(engine.records[BATH["objectID"]], OtherActivityDescription)
    assert BATH_TWIN["objectID"] not in engine.records
    assert engine.find_activity("bath").object_id == BATH["objectID"]
    folded = engine.records[rid(4)]
    assert isinstance(folded, OtherActivity) and folded.desc is not None
    assert folded.desc["objectID"] == BATH["objectID"]
    # A new activity of the type names the winner.
    added = await engine.add_activity(client, BABY_ID, "Bath", duration=5)
    assert added.desc is not None and added.desc["objectID"] == BATH["objectID"]


async def test_a_folded_entrys_records_count_as_the_winners_users(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    seed(fake_server, BATH, BATH_TWIN, activity_of(BATH, 3), activity_of(BATH_TWIN, 4))
    fake_server.add_transaction(PHONE, OP_CONFLICT, conflict(BATH, BATH_TWIN))
    engine = await synced(client)

    assert engine.entry_users(BATH["objectID"]) == 2
    assert engine.entry_users(BATH_TWIN["objectID"]) == 0
    with pytest.raises(EntryInUseError) as raised:
        await engine.delete_record(client, BATH["objectID"], any_device=True)
    assert raised.value.users == 2
    renamed = await engine.rename_entry(client, BATH["objectID"], "Bath time")
    assert isinstance(renamed, OtherActivityDescription)
    assert engine.find_activity("bath time").object_id == BATH["objectID"]

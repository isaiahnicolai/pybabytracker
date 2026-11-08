"""Vaccines: the pick list a record can name, and logging one."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import PROBE_UUID
from factories import BABY_ID, payload_for
from fake_server import FakeSyncServer

from pybabytracker import (
    BUILT_IN_VACCINES,
    OP_ADD,
    BabyTrackerClient,
    SyncEngine,
    UnknownVaccineError,
    Vaccine,
    VaccineSelection,
    decode_payload,
)

PHONE = "AAAA1111-0000-4000-8000-00000000000A"
EVENT_TIME = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
DTAP = "EasyLogSeed003effe4a50-8805-11e2-9e96-0800200c9a66"
# The record keys a vaccine shares with the Android milestone capture, plus vaccineType.
VACCINE_KEYS = {
    "BCObjectType",
    "vaccineType",
    "note",
    "pictureLoaded",
    "pictureNote",
    "time",
    "timezone",
    "newFlage",
    "objectID",
    "timestamp",
}


def rid(n: int) -> str:
    return f"AAAAAAAA-0000-4000-8000-{n:012d}"


def seed(server: FakeSyncServer, *payloads: dict[str, Any]) -> None:
    server.register_devices = False
    server.add_device(PHONE)
    server.add_transaction(PHONE, OP_ADD, payload_for("Diaper", rid(1)))
    for payload in payloads:
        server.add_transaction(PHONE, OP_ADD, payload)


async def synced(client: BabyTrackerClient) -> SyncEngine:
    engine = SyncEngine(device_uuid=PROBE_UUID)
    await engine.sync(client)
    return engine


def posted(server: FakeSyncServer) -> list[dict[str, Any]]:
    return [json.loads(base64.b64decode(e["Transaction"])) for e in server.posted(PROBE_UUID)]


def test_the_built_in_vaccines_are_the_apps_ten() -> None:
    assert [c.name for c in BUILT_IN_VACCINES] == [
        "HepB",
        "RV",
        "DTaP",
        "Hib",
        "PCV",
        "IPV",
        "Influenza",
        "MMR",
        "Varicella",
        "Hep A",
    ]
    assert all(c.object_id.startswith("EasyLogSeed") for c in BUILT_IN_VACCINES)
    assert BUILT_IN_VACCINES[2].selection["desc"] == "Diphtheria, Tetanus, Pertussis"


def test_a_synced_vaccine_selection_decodes() -> None:
    record = decode_payload(
        {"BCObjectType": "VaccineSelection", "objectID": "V-1", "name": "RSV", "forAge": 0}
    )
    assert isinstance(record, VaccineSelection)
    assert (record.name, record.for_age) == ("RSV", 0)


async def test_logging_a_built_in_vaccine_embeds_the_apps_seed(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    seed(fake_server)
    engine = await synced(client)

    record = await engine.add_vaccine(client, BABY_ID, "dtap", time=EVENT_TIME)

    assert isinstance(record, Vaccine)
    assert record.vaccine_name == "DTaP"
    [payload] = posted(fake_server)
    assert set(payload) - {"baby"} == VACCINE_KEYS
    assert payload["vaccineType"]["objectID"] == DTAP
    assert set(payload["vaccineType"]) == {
        "BCObjectType",
        "objectID",
        "name",
        "desc",
        "forAge",
        "newFlage",
        "timestamp",
    }


async def test_a_vaccine_added_in_the_app_is_offered_after_the_built_ins(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    rsv = {"BCObjectType": "VaccineSelection", "objectID": "V-1", "name": "RSV", "forAge": 0}
    seed(fake_server, rsv)
    engine = await synced(client)

    assert [c.name for c in engine.vaccine_choices()][-1] == "RSV"
    await engine.add_vaccine(client, BABY_ID, "RSV", time=EVENT_TIME)
    [payload] = posted(fake_server)
    assert payload["vaccineType"] == rsv


async def test_an_unknown_vaccine_is_refused_with_no_request(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    seed(fake_server)
    engine = await synced(client)
    before = len(fake_server.requests)

    with pytest.raises(UnknownVaccineError):
        await engine.add_vaccine(client, BABY_ID, "Smallpox", time=EVENT_TIME)
    with pytest.raises(ValueError):
        await engine.add_vaccine(client, BABY_ID, "", time=EVENT_TIME)
    assert len(fake_server.requests) == before

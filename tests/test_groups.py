"""Creating and resetting an account's sync group (invented data only)."""

from __future__ import annotations

from typing import Any

import pytest
from fake_server import FakeSyncServer

from pybabytracker import (
    AuthenticationError,
    BabyTrackerClient,
    BabyTrackerConnectionError,
    GroupExistsError,
    ProtocolError,
)
from pybabytracker import client as client_module

SEED = b"PK\x03\x04invented-seed-zip\r\n--not-a-boundary"
PHOTO = b"\xff\xd8\xff\xe0invented-photo\xff\xd9"
THUMBNAIL = b"\xff\xd8\xff\xe0invented-thumbnail\xff\xd9"
PICTURES = {"PHOTO-1.jpg": PHOTO, "PHOTO-1__thumbnail.jpg": THUMBNAIL}
SEED_BOUNDARY = "__BABY_TRACKER_BOUNDARY____SEED__"


def calls(server: FakeSyncServer) -> list[tuple[str, str]]:
    return [(r.method, r.path) for r in server.requests]


async def test_a_group_is_created_with_the_apps_four_steps(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.has_group = False
    old_account = fake_server.account_id

    await client.create_group(SEED, PICTURES)

    assert calls(fake_server) == [
        ("POST", "/staging_account"),
        ("POST", "/staging_account/seed"),
        ("POST", "/staging_account/picture"),
        ("POST", "/staging_account/picture"),
        ("PUT", "/staging_account"),
    ]
    start, seed_upload = fake_server.requests[0], fake_server.requests[1]
    # The first step carries the sign-in body.
    assert start.body["EmailAddress"] == fake_server.email
    assert start.body["AppInfo"] == {"AppType": 0, "AccountType": 0}
    assert set(start.body["Device"]) == {"DeviceUUID", "DeviceName", "DeviceOSInfo"}
    # The seed is framed as the app frames it.
    assert (
        seed_upload.body
        == (
            f"\r\n--{SEED_BOUNDARY}\r\n"
            'Content-Disposition: form-data; name="seed"; filename="seed.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode()
        + SEED
        + f"\r\n--{SEED_BOUNDARY}--\r\n".encode()
    )
    assert fake_server.has_group
    assert fake_server.account_id == old_account + 1
    assert (fake_server.seed, fake_server.pictures) == (SEED, PICTURES)


async def test_the_client_signs_in_to_the_new_group_on_its_next_call(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.has_group = False
    await client.create_group(SEED, PICTURES)
    assert client.account_id is None

    assert await client.get_seed() == SEED
    assert await client.get_picture("PHOTO-1__thumbnail.jpg") == THUMBNAIL
    assert client.account_id == fake_server.account_id


async def test_a_group_can_be_created_with_no_pictures(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.has_group = False

    await client.create_group(bytearray(SEED))

    assert [path for _, path in calls(fake_server)] == [
        "/staging_account",
        "/staging_account/seed",
        "/staging_account",
    ]
    assert fake_server.seed == SEED


async def test_creating_a_group_the_account_already_has_raises_and_changes_nothing(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.seed = b"PK\x03\x04the-old-seed"
    old_account = fake_server.account_id

    with pytest.raises(GroupExistsError):
        await client.create_group(SEED, PICTURES)

    assert calls(fake_server) == [("POST", "/staging_account")]
    assert (fake_server.account_id, fake_server.seed) == (old_account, b"PK\x03\x04the-old-seed")


async def test_a_reset_replaces_the_group_and_drops_its_devices(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    await client.get_devices()  # signed in, and a device on the old group
    fake_server.add_device("AAAA1111-0000-4000-8000-00000000000A")
    fake_server.seed = b"PK\x03\x04the-old-seed"
    old_account = fake_server.account_id
    fake_server.requests.clear()

    await client.reset_group(SEED, PICTURES, confirm_email=f"  {fake_server.email.upper()} ")

    assert calls(fake_server)[0] == ("POST", "/account_reset")
    assert calls(fake_server)[-1] == ("PUT", "/staging_account")
    assert fake_server.account_id == old_account + 1
    assert fake_server.devices == {} or list(fake_server.devices) == []
    assert (fake_server.seed, fake_server.pictures) == (SEED, PICTURES)
    assert client.account_id is None


@pytest.mark.parametrize("confirm", ["", "someone.else@example.test", None, 7])
async def test_a_reset_without_the_accounts_own_email_sends_nothing(
    client: BabyTrackerClient, fake_server: FakeSyncServer, confirm: Any
) -> None:
    with pytest.raises(ValueError):
        await client.reset_group(SEED, PICTURES, confirm_email=confirm)
    assert fake_server.requests == []


async def test_a_wrong_password_raises_authentication_error(
    fake_server: FakeSyncServer, client: BabyTrackerClient
) -> None:
    fake_server.password = "changed-since"
    old_account = fake_server.account_id

    with pytest.raises(AuthenticationError):
        await client.reset_group(SEED, confirm_email=fake_server.email)
    assert calls(fake_server) == [("POST", "/account_reset")]
    assert fake_server.account_id == old_account


@pytest.mark.parametrize(
    ("seed", "pictures"),
    [
        (b"", None),
        (b"not a zip", None),
        ("PK\x03\x04text", None),
        (None, None),
        (SEED, {"a/b.jpg": PHOTO}),
        (SEED, {"PHOTO-1.png": PHOTO}),
        (SEED, {'PHO"TO.jpg': PHOTO}),
        (SEED, {"PHOTO-1.jpg": b"\x89PNG\r\n\x1a\n"}),
        (SEED, {"PHOTO-1.jpg": "text"}),
        (SEED, [("PHOTO-1.jpg", PHOTO)]),
    ],
)
async def test_a_bad_seed_or_picture_is_refused_with_no_request(
    client: BabyTrackerClient, fake_server: FakeSyncServer, seed: Any, pictures: Any
) -> None:
    fake_server.has_group = False
    with pytest.raises(ValueError):
        await client.create_group(seed, pictures)
    with pytest.raises(ValueError):
        await client.reset_group(seed, pictures, confirm_email=fake_server.email)
    assert fake_server.requests == []


async def test_a_seed_over_the_limit_is_refused_with_no_request(
    client: BabyTrackerClient, fake_server: FakeSyncServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_server.has_group = False
    monkeypatch.setattr(client_module, "MAX_SEED_BYTES", len(SEED) - 1)

    with pytest.raises(ValueError):
        await client.create_group(SEED)
    assert fake_server.requests == []


@pytest.mark.parametrize(
    ("path", "status", "error"),
    [
        ("/staging_account/seed", 500, BabyTrackerConnectionError),
        ("/staging_account/seed", 400, ProtocolError),
        ("/staging_account/picture", 500, BabyTrackerConnectionError),
    ],
)
async def test_a_failed_upload_stops_before_the_group_is_replaced(
    client: BabyTrackerClient,
    fake_server: FakeSyncServer,
    path: str,
    status: int,
    error: type[Exception],
) -> None:
    fake_server.seed = b"PK\x03\x04the-old-seed"
    fake_server.fail_paths = {path: status}
    old_account = fake_server.account_id

    with pytest.raises(error):
        await client.reset_group(SEED, PICTURES, confirm_email=fake_server.email)

    assert ("PUT", "/staging_account") not in calls(fake_server)
    assert (fake_server.account_id, fake_server.seed) == (old_account, b"PK\x03\x04the-old-seed")


@pytest.mark.parametrize(
    ("status", "error"),
    [(424, ProtocolError), (409, GroupExistsError), (500, BabyTrackerConnectionError)],
)
async def test_a_refused_finish_raises_and_leaves_the_old_group(
    client: BabyTrackerClient, fake_server: FakeSyncServer, status: int, error: type[Exception]
) -> None:
    fake_server.finish_status = status
    old_account = fake_server.account_id
    await client.get_devices()
    signed_in_as = client.account_id

    with pytest.raises(error):
        await client.reset_group(SEED, PICTURES, confirm_email=fake_server.email)

    assert fake_server.account_id == old_account
    assert client.account_id == signed_in_as  # still the old group's client

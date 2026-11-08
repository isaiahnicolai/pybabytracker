"""Downloading picture files, and the file names a baby's photo has on the service."""

from __future__ import annotations

import pytest
from factories import baby_payload, payload_for
from fake_server import FakeSyncServer

from pybabytracker import (
    MEDIA_PHOTO,
    AuthenticationError,
    Baby,
    BabyTrackerClient,
    BabyTrackerConnectionError,
    Picture,
    decode_payload,
)

JPEG = b"\xff\xd8\xff\xe0invented-jpeg-bytes\xff\xd9"


async def test_a_picture_the_service_has_comes_back_as_its_bytes(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.pictures["PHOTO-1.jpg"] = JPEG

    assert await client.get_picture("PHOTO-1.jpg") == JPEG
    assert fake_server.calls("GET", "/account/picture/PHOTO-1.jpg")


@pytest.mark.parametrize("status", [400, 404])
async def test_a_picture_the_service_does_not_have_is_none(
    client: BabyTrackerClient, fake_server: FakeSyncServer, status: int
) -> None:
    fake_server.missing_picture_status = status
    assert await client.get_picture("MISSING.jpg") is None


async def test_an_expired_session_signs_in_again_for_a_picture(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.pictures["PHOTO-1.jpg"] = JPEG
    await client.get_picture("PHOTO-1.jpg")
    fake_server.sessions.clear()

    assert await client.get_picture("PHOTO-1.jpg") == JPEG


async def test_a_picture_the_service_keeps_rejecting_raises(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.always_unauthorized = True
    with pytest.raises(AuthenticationError):
        await client.get_picture("PHOTO-1.jpg")


async def test_a_server_error_for_a_picture_raises(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    fake_server.fail_paths["/PHOTO-1.jpg"] = 503
    with pytest.raises(BabyTrackerConnectionError):
        await client.get_picture("PHOTO-1.jpg")


@pytest.mark.parametrize("name", ["", "../secrets", "a/b.jpg", r"a\b.jpg", ".", ".."])
async def test_a_name_that_is_not_a_plain_file_name_is_refused_with_no_request(
    client: BabyTrackerClient, fake_server: FakeSyncServer, name: str
) -> None:
    with pytest.raises(ValueError):
        await client.get_picture(name)
    assert not fake_server.calls("GET", "/account/picture/" + name)


def _baby(picture_name: object) -> Baby:
    record = decode_payload(baby_payload(pictureName=picture_name))
    assert isinstance(record, Baby)
    return record


@pytest.mark.parametrize("picture_name", ["PHOTO-1", "PHOTO-1.jpg", "PHOTO-1.JPG"])
def test_a_babys_photo_files_add_the_apps_suffixes(picture_name: str) -> None:
    baby = _baby(picture_name)
    assert baby.picture_file == "PHOTO-1.jpg"
    assert baby.landscape_picture_file == "PHOTO-1_l.jpg"


@pytest.mark.parametrize("picture_name", [None, "", ".jpg", "a/b", r"..\x", 7])
def test_a_baby_without_a_usable_picture_name_has_no_files(picture_name: object) -> None:
    baby = _baby(picture_name)
    assert baby.picture_file is None
    assert baby.landscape_picture_file is None


def _entry(**overrides: object) -> dict[str, object]:
    """A pictureNote entry shaped like one an Android phone synced, with invented IDs."""
    entry: dict[str, object] = {
        "activityID": "ACTIVITY-1",
        "attached": True,
        "deleted": False,
        "fileName": "PICTURE-1",
        "mediaType": "0",
        "newFlage": True,
        "objectID": "PICTURE-ID-1",
        "timestamp": "2026-11-07 23:29:14 +0000",
    }
    entry.update(overrides)
    return entry


def _pictures(*entries: object) -> list[Picture]:
    record = decode_payload(payload_for("Milestone", pictureNote=list(entries)))
    return record.pictures


def test_a_photo_on_a_record_names_its_file_and_thumbnail() -> None:
    assert _pictures(_entry()) == [
        Picture(
            "PICTURE-ID-1", "PICTURE-1", MEDIA_PHOTO, "PICTURE-1.jpg", "PICTURE-1__thumbnail.jpg"
        )
    ]


@pytest.mark.parametrize(
    ("media_type", "file"), [(1, "PICTURE-1.mp4"), ("1", "PICTURE-1.mp4"), (0, "PICTURE-1.jpg")]
)
def test_a_videos_file_is_mp4_and_either_form_of_media_type_reads(
    media_type: object, file: str
) -> None:
    [picture] = _pictures(_entry(mediaType=media_type))
    assert picture.file == file
    assert picture.thumbnail_file == "PICTURE-1__thumbnail.jpg"


def test_an_unknown_media_type_still_has_a_thumbnail_but_no_file() -> None:
    [picture] = _pictures(_entry(mediaType="2"))
    assert (picture.media_type, picture.file) == (2, None)


@pytest.mark.parametrize(
    "entry",
    [
        _entry(deleted=True),
        _entry(deleted="true"),
        _entry(fileName=""),
        _entry(fileName="../PICTURE-1"),
        _entry(fileName=7),
        "PICTURE-1",
    ],
)
def test_deleted_and_unusable_entries_are_left_out(entry: object) -> None:
    assert _pictures(entry, _entry(fileName="PICTURE-2")) == [
        Picture(
            "PICTURE-ID-1", "PICTURE-2", MEDIA_PHOTO, "PICTURE-2.jpg", "PICTURE-2__thumbnail.jpg"
        )
    ]


@pytest.mark.parametrize("picture_note", [None, [], "not a list"])
def test_a_record_without_pictures_has_none(picture_note: object) -> None:
    record = decode_payload(payload_for("Diaper", pictureNote=picture_note))
    assert record.pictures == []

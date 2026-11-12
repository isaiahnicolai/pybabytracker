"""Asking for a password reset email."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from conftest import PROBE_UUID
from fake_server import FakeSyncServer

from pybabytracker import (
    AuthenticationError,
    BabyTrackerClient,
    BabyTrackerConnectionError,
    NoResponseError,
    ProtocolError,
    UnknownAccountError,
)


def other_client(
    fake_server: FakeSyncServer, session: aiohttp.ClientSession, email: str, **extra: Any
) -> BabyTrackerClient:
    return BabyTrackerClient(
        email,
        "irrelevant",
        PROBE_UUID,
        "Test Device",
        session=session,
        base_url=fake_server.base_url,
        **extra,
    )


async def test_the_request_is_the_one_the_app_sends_and_needs_no_session(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    await client.request_password_reset()

    [request] = fake_server.requests
    assert (request.method, request.path) == ("POST", "/account/forgot_password")
    assert request.body == {
        "EmailAddress": fake_server.email,
        "Language": "en",
        "AppInfo": {"AccountType": 0, "AppType": 0},
    }
    assert str(request.user_agent).startswith("pybabytracker/")
    assert fake_server.reset_emails == 1
    assert fake_server.sessions == {}  # no sign-in was made


async def test_the_language_is_sent_in_lower_case(
    client: BabyTrackerClient, fake_server: FakeSyncServer
) -> None:
    await client.request_password_reset("ES")
    assert fake_server.requests[-1].body["Language"] == "es"


async def test_an_address_with_no_account_raises_unknown_account(
    fake_server: FakeSyncServer, session: aiohttp.ClientSession
) -> None:
    stranger = other_client(fake_server, session, "nobody@example.test")

    with pytest.raises(UnknownAccountError) as raised:
        await stranger.request_password_reset()
    assert isinstance(raised.value, AuthenticationError)
    assert fake_server.reset_emails == 0


@pytest.mark.parametrize(
    ("status", "error"), [(500, BabyTrackerConnectionError), (409, ProtocolError)]
)
async def test_another_error_status_raises(
    client: BabyTrackerClient,
    fake_server: FakeSyncServer,
    status: int,
    error: type[Exception],
) -> None:
    fake_server.force_status = status
    with pytest.raises(error):
        await client.request_password_reset()
    assert fake_server.reset_emails == 0


async def test_no_answer_raises_no_response(
    fake_server: FakeSyncServer, session: aiohttp.ClientSession
) -> None:
    quick = other_client(fake_server, session, fake_server.email, request_timeout=0.2)
    fake_server.delay = 0.6

    with pytest.raises(NoResponseError):
        await quick.request_password_reset()


@pytest.mark.parametrize("language", ["", "e", "english", "e1", 7, None])
async def test_a_bad_language_is_refused_with_no_request(
    client: BabyTrackerClient, fake_server: FakeSyncServer, language: Any
) -> None:
    with pytest.raises(ValueError):
        await client.request_password_reset(language)
    assert fake_server.requests == []

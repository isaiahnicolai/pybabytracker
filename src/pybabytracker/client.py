"""Async client for the sync service: sign in, list devices, read a device's log."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote

import aiohttp

from ._version import __version__
from .exceptions import (
    AccountChangedError,
    AccountResetError,
    AuthenticationError,
    BabyTrackerConnectionError,
    DownloadRefusedError,
    GroupExistsError,
    NoResponseError,
    ProtocolError,
    UnknownAccountError,
)
from .models import MAX_PICTURE_BYTES, check_jpeg, is_account_id, is_plain_file_name

_LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://prodapp.babytrackers.com"
DEFAULT_TIMEOUT = 30.0
USER_AGENT = f"pybabytracker/{__version__}"
MAX_SEED_BYTES = 64 * 1024 * 1024
# The multipart boundary the apps use for a picture upload.
_PICTURE_BOUNDARY = "__BABY_TRACKER_BOUNDARY____Photo__"
# The multipart boundary the apps use for a seed upload, and how a zip file starts.
_SEED_BOUNDARY = "__BABY_TRACKER_BOUNDARY____SEED__"
_ZIP_START = b"PK\x03\x04"
# A seed can be large, so it gets longer than other requests, as long as data keeps coming.
SEED_TIMEOUT = 600.0


@dataclass(frozen=True, slots=True)
class Device:
    """One device in the account's sync group."""

    device_uuid: str
    last_sync_id: int
    device_name: str
    device_os_info: str


@dataclass(frozen=True, slots=True)
class RawTransaction:
    """One entry from a device's log, with the payload still base64 encoded."""

    sync_id: int
    op_code: int
    transaction: str


class BabyTrackerClient:
    """Talks to the sync service as one device in the account's sync group.

    Pass ``session`` to use an ``aiohttp.ClientSession`` (the client never closes it).
    Without one, the client makes its own on first use and closes it in ``close()``.

    The service authenticates by cookie, so the session must be dedicated to this client. Don't
    share one session between two accounts (in Home Assistant, use
    ``async_create_clientsession``, not the shared ``async_get_clientsession``).

    ``unsafe_cookie_jar`` only affects a session the client makes itself: it lets cookies from
    an IP-address host through, which only a local test server needs.
    """

    def __init__(
        self,
        email: str,
        password: str,
        device_uuid: str,
        device_name: str,
        *,
        session: aiohttp.ClientSession | None = None,
        base_url: str = DEFAULT_BASE_URL,
        device_os_info: str = USER_AGENT,
        request_timeout: float = DEFAULT_TIMEOUT,
        unsafe_cookie_jar: bool = False,
    ) -> None:
        self._email = email
        self._password = password
        self._device_uuid = device_uuid
        self._device_name = device_name
        self._device_os_info = device_os_info
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._session = session
        self._owns_session = session is None
        self._unsafe_cookie_jar = unsafe_cookie_jar
        self._sign_in_lock = asyncio.Lock()
        self._generation = 0  # counts successful sign-ins
        self._signed_in = False
        self._account_id: int | None = None

    def __repr__(self) -> str:
        return f"BabyTrackerClient(device_uuid={self._device_uuid!r}, base_url={self._base_url!r})"

    @property
    def device_uuid(self) -> str:
        """The device this client signs in and posts as."""
        return self._device_uuid

    @property
    def account_id(self) -> int | None:
        return self._account_id

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the session if this client made it. A passed-in session is left open."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def sign_in(self) -> int:
        """Start a session. Raises ``AuthenticationError`` if the credentials are rejected, and
        ``AccountResetError`` if the service refuses this device because the account was reset.

        Raises ``AccountChangedError`` if this client already signed in to a different sync
        group, which includes a sign-in made to recover from a 401 inside another call. The
        call that needed it is not retried.
        """
        async with self._sign_in_lock:
            return await self._sign_in()

    def _user_info(self) -> dict[str, Any]:
        """The body the apps post to sign in, and to create or reset a group."""
        return {
            "EmailAddress": self._email,
            "Password": self._password,
            "Device": {
                "DeviceUUID": self._device_uuid,
                "DeviceName": self._device_name,
                "DeviceOSInfo": self._device_os_info,
            },
            "AppInfo": {"AppType": 0, "AccountType": 0},
        }

    async def _sign_in(self) -> int:
        self._signed_in = False
        status, text = await self._send("POST", "/session", self._user_info())
        if status == 401 and _is_reset_reply(text):
            # Every device from before a reset is refused; the app joins as a new device.
            raise AccountResetError(self._account_id)
        if status in (401, 403):
            raise AuthenticationError("the service rejected the email or password")
        _raise_for_status(status)
        data = _parse_json(text)
        account_id = data.get("AccountID") if isinstance(data, dict) else None
        if not is_account_id(account_id):
            raise ProtocolError("sign-in reply had no AccountID")
        if self._account_id is not None and account_id != self._account_id:
            # The sync group was reset. Stay signed out, so nothing more is sent to the new one.
            raise AccountChangedError(self._account_id, account_id)
        self._signed_in = True
        self._generation += 1
        self._account_id = account_id
        return account_id

    async def sign_out(self) -> None:
        """End the session, as the app does when it disconnects: ``DELETE /session``.

        The service answers ``200``, and ``401`` when the session had already ended; both leave
        this client signed out, and a ``401`` here never signs in again. Nothing is sent when
        the client isn't signed in. The client stays usable: its next call signs in. Any other
        error status, or no answer, raises as for the other calls, and the client then still
        counts as signed in.
        """
        async with self._sign_in_lock:
            if not self._signed_in:
                return
            status, _ = await self._send("DELETE", "/session")
            if status != 401:
                _raise_for_status(status)
            self._signed_in = False

    async def request_password_reset(self, language: str = "en") -> None:
        """Ask the service to email this client's address a link to reset the password, as the
        app's "forgot password" screen does: ``POST /account/forgot_password``.

        No session is needed and none is made. ``language`` is the two-letter code the app
        sends from the phone's locale. The service answers ``200`` when the email is on its
        way, and ``400`` when it has no account for the address, which raises
        ``UnknownAccountError``. Any other error status, or no answer, raises as for the other
        calls. The password itself doesn't change until the link is used.
        """
        if not isinstance(language, str) or not (2 <= len(language) <= 3 and language.isalpha()):
            raise ValueError("language must be a two- or three-letter language code")
        status, _ = await self._send(
            "POST",
            "/account/forgot_password",
            {
                "EmailAddress": self._email,
                "Language": language.lower(),
                "AppInfo": {"AccountType": 0, "AppType": 0},
            },
        )
        if status == 400:
            raise UnknownAccountError("the service has no account for this email address")
        _raise_for_status(status)

    async def create_group(
        self, seed: bytes | bytearray, pictures: Mapping[str, bytes] | None = None
    ) -> None:
        """Create the account's sync group from a seed, as the app does when sync is first
        turned on. For an address the service doesn't know, this also creates the account.

        ``seed`` is the zip of the app's database, in the form ``get_seed`` returns one.
        ``pictures`` maps each picture file's name (as ``upload_picture`` takes it) to its JPEG
        bytes. The steps are the app's: ``POST /staging_account`` with the sign-in body, the
        seed to ``/staging_account/seed``, each picture to ``/staging_account/picture``, and
        ``PUT /staging_account`` to finish. Nothing replaces the group until the last step.

        ``GroupExistsError`` means the account already has a group (use ``reset_group``),
        ``AuthenticationError`` that the password was refused, and ``ProtocolError`` that the
        service couldn't build the group from what was staged. A seed that isn't a zip or is
        over ``MAX_SEED_BYTES``, or a bad picture name or file, raises ``ValueError`` before
        any request.

        The app takes a new device ID before it creates a group, so use a client with a new
        ``device_uuid``. Afterwards this client is signed out; its next call signs in to the
        new group, and a ``SyncEngine`` for it must be new.
        """
        await self._build_group("/staging_account", seed, pictures)

    async def reset_group(
        self,
        seed: bytes | bytearray,
        pictures: Mapping[str, bytes] | None = None,
        *,
        confirm_email: str,
    ) -> None:
        """Replace the account's sync group with one built from a seed, as the app's "reset
        sync" does. **This discards every device's log and removes every device from the
        group:** each phone has to join again, and only what is in ``seed`` survives.

        It is ``create_group`` with ``POST /account_reset`` as the first step, and takes the
        same ``seed`` and ``pictures``. ``confirm_email`` must be this client's email address,
        or nothing is sent: it is there so a reset can't happen by a stray call.

        Every device from before a reset is refused afterwards (``AccountResetError``), this
        client's included, so use a client with a new ``device_uuid``, as the app does.
        """
        if not isinstance(confirm_email, str) or (
            confirm_email.strip().casefold() != self._email.strip().casefold()
        ):
            raise ValueError("confirm_email must be this client's email address")
        await self._build_group("/account_reset", seed, pictures)

    async def _build_group(
        self, start: str, seed: bytes | bytearray, pictures: Mapping[str, bytes] | None
    ) -> None:
        if not isinstance(seed, bytes | bytearray) or not bytes(seed).startswith(_ZIP_START):
            raise ValueError("a seed must be the bytes of a zip file")
        if len(seed) > MAX_SEED_BYTES:
            raise ValueError(f"a seed can't be more than {MAX_SEED_BYTES} bytes")
        if pictures is not None and not isinstance(pictures, Mapping):
            raise ValueError("pictures must map each file name to its JPEG bytes")
        files = [
            (_picture_file_name(name), check_jpeg(data, "a picture"))
            for name, data in (pictures or {}).items()
        ]
        seed_form = _form(_SEED_BOUNDARY, "seed", "seed.zip", "application/zip", bytes(seed))
        slow = aiohttp.ClientTimeout(total=SEED_TIMEOUT, sock_read=self._timeout.total)
        async with self._sign_in_lock:
            status, _ = await self._send("POST", start, self._user_info())
            if status in (401, 403):
                raise AuthenticationError("the service rejected the email or password")
            if status == 409:
                raise GroupExistsError("the account already has a sync group")
            _raise_for_status(status)
            await self._stage("/staging_account/seed", _SEED_BOUNDARY, seed_form, slow)
            for name, jpeg in files:
                form = _form(_PICTURE_BOUNDARY, "picture", name, "image/jpeg", jpeg)
                await self._stage("/staging_account/picture", _PICTURE_BOUNDARY, form, None)
            status, _ = await self._send("PUT", "/staging_account")
            if status == 424:
                raise ProtocolError("the service could not build the group from the staged seed")
            if status == 409:
                raise GroupExistsError("the account already has a sync group")
            _raise_for_status(status)
            # The old session and AccountID belong to the group that was replaced.
            self._signed_in = False
            self._account_id = None

    async def _stage(
        self, path: str, boundary: str, form: bytes, limits: aiohttp.ClientTimeout | None
    ) -> None:
        """Post one multipart file to the staging area of a group being built."""
        status, _ = await self._exchange(
            "POST",
            path,
            None,
            lambda response: response.text(),
            allow_redirects=False,
            limits=limits,
            data=form,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        if status == 401:
            raise AuthenticationError("the service rejected the staging session")
        if 300 <= status < 400:
            raise ProtocolError(f"the service redirected the staging upload (HTTP {status})")
        _raise_for_status(status)

    async def get_devices(self) -> list[Device]:
        """Every device in the sync group, with its last transaction number."""
        data = await self._request("GET", "/account/device")
        if not isinstance(data, list):
            raise ProtocolError("device list was not a JSON array")
        try:
            return [
                Device(
                    device_uuid=str(entry["DeviceUUID"]),
                    last_sync_id=int(entry["LastSyncID"]),
                    device_name=str(entry["DeviceName"]),
                    device_os_info=str(entry["DeviceOSInfo"]),
                )
                for entry in data
            ]
        except (KeyError, TypeError, ValueError) as err:
            raise ProtocolError(f"malformed device entry: {err!r}") from err

    async def get_transactions(
        self, device_uuid: str, since_sync_id: int = 0
    ) -> list[RawTransaction]:
        """A device's transactions after ``since_sync_id``, in the order the service sends them."""
        path = f"/account/transaction/{quote(device_uuid, safe='')}/{int(since_sync_id)}"
        data = await self._request("GET", path)
        if not isinstance(data, list):
            raise ProtocolError("transaction list was not a JSON array")
        transactions: list[RawTransaction] = []
        for entry in data:
            parsed = _parse_entry(entry)
            if parsed is None:
                _LOGGER.warning("Dropping a log entry with no usable SyncID from %s", device_uuid)
            else:
                transactions.append(parsed)
        if data and not transactions:
            raise ProtocolError("no entry in the transaction list had a usable SyncID")
        return transactions

    async def post_transaction(self, op_code: int, sync_id: int, transaction: str) -> None:
        """Append one transaction to this device's log as number ``sync_id``.

        This is the raw call. It doesn't choose numbers or check whether a failed post landed;
        ``SyncEngine``'s write methods do both. A 401 retry resends the same number, which is
        safe because a 401 means the service didn't accept the post.
        """
        await self._request(
            "POST",
            "/account/transaction",
            {"OPCode": int(op_code), "SyncID": int(sync_id), "Transaction": transaction},
            expect_json=False,
        )

    async def get_picture(self, file_name: str) -> bytes | None:
        """Download a picture file, such as a baby's photo (``Baby.picture_file``).

        Returns ``None`` when the service doesn't have the file: it has answered ``400`` for a
        file it doesn't have (seen for a photo's ".mp4" name), and ``404`` is expected, not yet
        seen, so both mean no file. Any other error status raises, as for the other calls.

        A redirect raises ``ProtocolError`` and is not followed. A body over ``MAX_PICTURE_BYTES``
        raises ``DownloadRefusedError`` (a ``ProtocolError``). A name that is empty, only
        whitespace, not a string, or has a path separator raises ``ValueError`` without a request:
        names come from other devices' records.
        """
        if not is_plain_file_name(file_name):
            raise ValueError(f"not a picture file name: {file_name!r}")
        path = f"/account/picture/{quote(file_name, safe='')}"
        status, content = await self._authorized(
            lambda: self._send_bytes(path, MAX_PICTURE_BYTES), allow=(400, 404)
        )
        if 300 <= status < 400:
            raise ProtocolError(f"the service redirected the picture request (HTTP {status})")
        return None if status in (400, 404) else content

    async def upload_picture(self, file_name: str, data: bytes | bytearray) -> None:
        """Upload a JPEG picture file, for a record's ``pictureNote`` to name.

        ``file_name`` is the name other devices download it by: a photo is the picture's
        ``fileName`` plus ".jpg", and its thumbnail is ``fileName`` plus "__thumbnail.jpg"
        (``Picture.file`` and ``Picture.thumbnail_file``). The apps upload both, and the files
        before the record that names them, since other devices fetch a picture as soon as they
        merge its record. Uploading a name again is expected to replace the file (seen only
        against a fake service, not yet live).

        The request is the one the apps send: a multipart POST of the file in a ``picture``
        field, with the name as its ``filename`` and type ``image/jpeg``. The apps expect
        ``201``; any 2xx counts here. A 401 signs in again and sends it again, which is safe
        because the file is named. No answer at all raises ``NoResponseError``, and the file may
        or may not have landed, so upload it again. A redirect raises ``ProtocolError`` and is not
        followed, since a redirected POST can come back 2xx without storing the file.

        ``data`` must be a JPEG (videos aren't supported) of at most ``MAX_PICTURE_BYTES``. A
        name that doesn't end ".jpg", isn't a plain file name, or has a quote or a line break
        raises ``ValueError`` without a request, as does data that isn't a JPEG or is too large.
        """
        if (
            not is_plain_file_name(file_name)
            or not file_name.endswith(".jpg")
            or not is_plain_file_name(file_name.removesuffix(".jpg"))
            or any(c in file_name for c in '"\r\n')
        ):
            raise ValueError(f"not a picture file name: {file_name!r}")
        jpeg = check_jpeg(data, "a picture")
        head = (
            f"\r\n--{_PICTURE_BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="picture"; filename="{file_name}"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        tail = f"\r\n--{_PICTURE_BOUNDARY}--\r\n".encode()
        body = head + jpeg + tail
        content_type = f"multipart/form-data; boundary={_PICTURE_BOUNDARY}"
        status, _ = await self._authorized(
            lambda: self._exchange(
                "POST",
                "/account/picture",
                None,
                lambda response: response.text(),
                allow_redirects=False,
                data=body,
                content_type=content_type,
            )
        )
        if 300 <= status < 400:
            raise ProtocolError(f"the service redirected the picture upload (HTTP {status})")

    async def get_seed(self) -> bytes | None:
        """Download the account's seed: a zip with a full copy of the account's database.

        The transaction logs don't hold the whole history. Records from devices that have since
        left the account are only in the seed, so read it before the logs (``read_seed`` and
        ``SyncEngine.sync`` do this). Returns ``None`` when the account has no seed: an empty
        body, or a ``400`` or ``404`` (expected, not yet seen).

        A redirect raises ``ProtocolError`` and is not followed. A body over ``MAX_SEED_BYTES``
        raises ``DownloadRefusedError`` (a ``ProtocolError``). The download may take up to
        ``SEED_TIMEOUT`` seconds in all, but fails if the service goes quiet for the client's usual
        request timeout.
        """
        limits = aiohttp.ClientTimeout(total=SEED_TIMEOUT, sock_read=self._timeout.total)
        status, content = await self._authorized(
            lambda: self._send_bytes("/account/seed", MAX_SEED_BYTES, limits), allow=(400, 404)
        )
        if 300 <= status < 400:
            raise ProtocolError(f"the service redirected the seed request (HTTP {status})")
        return content if status not in (400, 404) and content else None

    async def _request(
        self, method: str, path: str, body: Any = None, *, expect_json: bool = True
    ) -> Any:
        """Call an endpoint that needs a session.

        A 401 means the session expired: sign in again once and retry. A second 401 raises.
        With ``expect_json`` false, any 2xx answer counts and its body is ignored.
        """
        _, text = await self._authorized(lambda: self._send(method, path, body))
        return _parse_json(text) if expect_json else None

    async def _authorized[T](
        self, send: Callable[[], Awaitable[tuple[int, T]]], *, allow: tuple[int, ...] = ()
    ) -> tuple[int, T]:
        """Run ``send`` with a session, signing in again once on a 401.

        A status in ``allow`` is returned as is; any other error status raises.
        """
        if not self._signed_in:
            async with self._sign_in_lock:
                if not self._signed_in:
                    await self._sign_in()
        for attempt in range(2):
            generation = self._generation
            status, content = await send()
            if status != 401:
                if status not in allow:
                    _raise_for_status(status)
                return status, content
            if attempt == 1:
                self._signed_in = False
                break
            async with self._sign_in_lock:
                # Skip it if another task signed in again while this one waited.
                if self._generation == generation:
                    await self._sign_in()
        raise AuthenticationError("the service rejected the session even after signing in again")

    async def _send(self, method: str, path: str, body: Any = None) -> tuple[int, str]:
        return await self._exchange(method, path, body, lambda response: response.text())

    async def _send_bytes(
        self, path: str, cap: int, limits: aiohttp.ClientTimeout | None = None
    ) -> tuple[int, bytes]:
        read = partial(_read_capped, cap=cap)
        return await self._exchange("GET", path, None, read, allow_redirects=False, limits=limits)

    async def _exchange[T](
        self,
        method: str,
        path: str,
        body: Any,
        read: Callable[[aiohttp.ClientResponse], Awaitable[T]],
        *,
        allow_redirects: bool = True,
        limits: aiohttp.ClientTimeout | None = None,
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> tuple[int, T]:
        """Send a request with a JSON ``body``, or else raw ``data`` of ``content_type``."""
        if self._session is None:
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(unsafe=self._unsafe_cookie_jar)
            )
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                json=body if data is None else None,
                data=data,
                headers=(
                    {"User-Agent": USER_AGENT}
                    if content_type is None
                    else {"User-Agent": USER_AGENT, "Content-Type": content_type}
                ),
                timeout=limits or self._timeout,
                allow_redirects=allow_redirects,
            ) as response:
                return response.status, await read(response)
        except aiohttp.ClientConnectorError as err:
            # No connection was made, so the request never reached the service.
            raise BabyTrackerConnectionError(f"could not reach the service: {err!r}") from err
        except (aiohttp.ClientError, TimeoutError) as err:
            # Sent, but no answer came back: the service may or may not have acted on it.
            raise NoResponseError(f"no answer from the service: {err!r}") from err


def _picture_file_name(file_name: object) -> str:
    """A picture file's name as the service takes it, or ``ValueError``: a plain ".jpg" name
    with no quote or line break, since it goes into a header line."""
    if (
        not isinstance(file_name, str)
        or not is_plain_file_name(file_name)
        or not file_name.endswith(".jpg")
        or not is_plain_file_name(file_name.removesuffix(".jpg"))
        or any(c in file_name for c in '"\r\n')
    ):
        raise ValueError(f"not a picture file name: {file_name!r}")
    return file_name


def _form(boundary: str, field: str, file_name: str, mime: str, data: bytes) -> bytes:
    """One file as the apps frame a multipart upload."""
    head = (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{file_name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode()
    return head + data + f"\r\n--{boundary}--\r\n".encode()


async def _read_capped(response: aiohttp.ClientResponse, *, cap: int) -> bytes:
    """The body of ``response``, or ``DownloadRefusedError`` when it's over ``cap`` bytes.

    A redirect or an error status has its body skipped, since only the status is used.
    """
    if response.status >= 300:
        return b""
    if response.content_length is not None and response.content_length > cap:
        raise DownloadRefusedError(f"the download is larger than {cap} bytes")
    body = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        body += chunk
        if len(body) > cap:
            raise DownloadRefusedError(f"the download is larger than {cap} bytes")
    return bytes(body)


def _parse_entry(entry: Any) -> RawTransaction | None:
    """A log entry, or None with no usable SyncID.

    An entry whose other fields are bad still comes back, as a placeholder (opcode -1, empty
    payload) that the engine skips, so the sync number still advances past it.
    """
    if not isinstance(entry, dict):
        return None
    try:
        sync_id = int(entry["SyncID"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        payload = entry["Transaction"]
        if not isinstance(payload, str):
            raise TypeError("Transaction is not a string")
        return RawTransaction(sync_id, int(entry["OPCode"]), payload)
    except (KeyError, TypeError, ValueError):
        _LOGGER.warning("Log entry %s is malformed; it will be skipped", sync_id)
        return RawTransaction(sync_id, -1, "")


_RESET_REPLY = re.compile(r"\baccount\s+has\s+been\s+reset\b", re.IGNORECASE)


def _is_reset_reply(text: str) -> bool:
    """Whether a refused sign-in says the account was reset, not that the password is wrong.

    The service answers a device from before a reset with "Account has been reset. Please login
    again". Only that phrase counts, in any case and spacing: "Your password has been reset", say,
    is still a rejected password.
    """
    return _RESET_REPLY.search(text) is not None


def _raise_for_status(status: int) -> None:
    if status >= 500:
        raise BabyTrackerConnectionError(f"the service answered with HTTP {status}")
    if status >= 400:
        raise ProtocolError(f"the service answered with HTTP {status}")


def _parse_json(text: str) -> Any:
    # The service labels its JSON as text/html, so parse the text ourselves.
    try:
        return json.loads(text)
    except ValueError as err:
        raise ProtocolError("the service did not answer with JSON") from err

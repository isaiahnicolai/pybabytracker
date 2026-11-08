"""The app's milestone pick list: the milestones it ships with, and how a record names one.

A ``Milestone`` record embeds the milestone it marks (a ``MilestoneSelection``) as
``milestoneType``. The built-in milestones aren't on the service: every app seeds them locally
under fixed IDs starting ``EasyLogSeed`` (app: ``BTSQLiteOpenHelper`` seed rows,
``DefaultValues.DefaultSeedPrefix``), so a record that names one must use the same ID for the app
to match it. Milestones a user adds sync as ``MilestoneSelection`` transactions of their own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# The timestamp the app gives its seeded selections.
_SEED_TIMESTAMP = "1970-01-01 00:00:00 +0000"

# The app's built-in milestones, in its order: ID, name, and the description it shows after the
# baby's name ("<name> came home"). The leading space or "'s" is part of the description.
_BUILT_IN_MILESTONES: tuple[tuple[str, str, str], ...] = (
    ("EasyLogSeed3b250600-894f-11e2-9e96-0800200c9a66", "Back home", " came home"),
    (
        "EasyLogSeed44720140-894f-11e2-9e96-0800200c9a66",
        "Recognizes caregiver’s voice",
        " recognized our voice",
    ),
    (
        "EasyLogSeedb5196be0-894f-11e2-9e96-0800200c9a66",
        "Recognizes familiar faces",
        " recognizes familiar faces",
    ),
    ("EasyLogSeed56cc56b0-894f-11e2-9e96-0800200c9a66", "First smile", "'s first smile"),
    ("EasyLogSeed5ecef7a0-894f-11e2-9e96-0800200c9a66", "Raise head", " lifted head up"),
    ("EasyLogSeed773fae60-894f-11e2-9e96-0800200c9a66", "Claps Hand", " claps hand"),
    (
        "EasyLogSeed852cb5a0-b815-11e2-9e96-0800200c9a66",
        "Slept through the night",
        " slept through the night",
    ),
    ("EasyLogSeed8ca15060-894f-11e2-9e96-0800200c9a66", "Laughs out loud", "'s first laugh"),
    ("EasyLogSeed96964b70-894f-11e2-9e96-0800200c9a66", "Babbles", " babbles"),
    ("EasyLogSeeda0faf840-894f-11e2-9e96-0800200c9a66", "Holds head steady", "  holds head up"),
    (
        "EasyLogSeeda7ef3670-894f-11e2-9e96-0800200c9a66",
        "Responds to own name",
        " responds when called",
    ),
    ("EasyLogSeedbd0eed70-894f-11e2-9e96-0800200c9a66", "Rolls over", " rolls over"),
    ("EasyLogSeed00932210-b816-11e2-9e96-0800200c9a66", "Sits up", " sits up"),
    ("EasyLogSeed22db0820-b815-11e2-9e96-0800200c9a66", "First tooth", "'s first tooth"),
    ("EasyLogSeedd3559840-894f-11e2-9e96-0800200c9a66", "Says mama", " says mama"),
    ("EasyLogSeeddaf4e380-894f-11e2-9e96-0800200c9a66", "Says dada", " says dada"),
    ("EasyLogSeed7b293110-b814-11e2-9e96-0800200c9a66", "First word", " says first word"),
    ("EasyLogSeed662c00c0-b815-11e2-9e96-0800200c9a66", "Waves Bye-Bye", " waves Bye-Bye"),
    ("EasyLogSeed2dae38c0-b816-11e2-9e96-0800200c9a66", "Stands up", " stands up"),
    ("EasyLogSeed4f6c38e0-b816-11e2-9e96-0800200c9a66", "First steps", "'s first steps"),
)


@dataclass(frozen=True, slots=True)
class MilestoneChoice:
    """A milestone a record can name: its ID, its name, and the object a record embeds."""

    object_id: str
    name: str
    built_in: bool
    selection: Mapping[str, Any] = field(compare=False, repr=False)


def _built_in(object_id: str, name: str, desc: str) -> MilestoneChoice:
    return MilestoneChoice(
        object_id=object_id,
        name=name,
        built_in=True,
        selection={
            "BCObjectType": "MilestoneSelection",
            "objectID": object_id,
            "name": name,
            "desc": desc,
            "forAge": 0,
            "used": "false",
            "newFlage": "false",
            "timestamp": _SEED_TIMESTAMP,
        },
    )


BUILT_IN_MILESTONES: tuple[MilestoneChoice, ...] = tuple(
    _built_in(*row) for row in _BUILT_IN_MILESTONES
)


def choice_from_selection(selection: object, *, built_in: bool = False) -> MilestoneChoice | None:
    """A choice for a ``MilestoneSelection`` object, or ``None`` without a string ID and name."""
    if not isinstance(selection, Mapping):
        return None
    object_id, name = selection.get("objectID"), selection.get("name")
    if not isinstance(object_id, str) or not object_id or not isinstance(name, str):
        return None
    return MilestoneChoice(object_id, name, built_in, dict(selection))

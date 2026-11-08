"""The app's pick lists: the milestones and vaccines it ships with, and how a record names one.

A ``Milestone`` record embeds the milestone it marks (a ``MilestoneSelection``) as
``milestoneType``. The built-in milestones aren't on the service: every app seeds them locally
under fixed IDs starting ``EasyLogSeed`` (app: ``BTSQLiteOpenHelper`` seed rows,
``DefaultValues.DefaultSeedPrefix``), so a record that names one must use the same ID for the app
to match it. Milestones a user adds sync as ``MilestoneSelection`` transactions of their own.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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
class SelectionChoice:
    """An entry of a pick list a record can name (a milestone, a vaccine, a medicine): its ID,
    its name, whether the app ships it, and the object a record embeds."""

    object_id: str
    name: str
    built_in: bool
    selection: Mapping[str, Any] = field(compare=False, repr=False)


# A milestone choice; the name is kept for the milestone API.
MilestoneChoice = SelectionChoice

# The app's built-in vaccines, in its order: ID, short name, and full name. The app seeds every
# one with forAge 0.
_BUILT_IN_VACCINES: tuple[tuple[str, str, str], ...] = (
    ("EasyLogSeed001ddeae8f0-8805-11e2-9e96-0800200c9a66", "HepB", "Hepatitis B"),
    ("EasyLogSeed002e733ec90-8805-11e2-9e96-0800200c9a66", "RV", "Rotavirus"),
    (
        "EasyLogSeed003effe4a50-8805-11e2-9e96-0800200c9a66",
        "DTaP",
        "Diphtheria, Tetanus, Pertussis",
    ),
    (
        "EasyLogSeed004f8ab3500-8805-11e2-9e96-0800200c9a66",
        "Hib",
        "Haemophilus influenzae type b",
    ),
    ("EasyLogSeed0050051d340-8806-11e2-9e96-0800200c9a66", "PCV", "Pneumococcal"),
    ("EasyLogSeed0060838fcf0-8806-11e2-9e96-0800200c9a66", "IPV", "Inactivated Poliovirus"),
    ("EasyLogSeed007132f8980-8806-11e2-9e96-0800200c9a66", "Influenza", "Influenza"),
    ("EasyLogSeed0081d5383d0-8806-11e2-9e96-0800200c9a66", "MMR", "Measles, Mumps, Rubella"),
    ("EasyLogSeed00925268940-8806-11e2-9e96-0800200c9a66", "Varicella", "Varicella"),
    ("EasyLogSeed0102d1f1810-8806-11e2-9e96-0800200c9a66", "Hep A", "Hepatitis A"),
)


def _seed(object_type: str, object_id: str, name: str, desc: str, **extra: Any) -> SelectionChoice:
    """A built-in entry as the app seeds it, in the shape a record embeds."""
    return SelectionChoice(
        object_id=object_id,
        name=name,
        built_in=True,
        selection={
            "BCObjectType": object_type,
            "objectID": object_id,
            "name": name,
            "desc": desc,
            **extra,
            "newFlage": "false",
            "timestamp": _SEED_TIMESTAMP,
        },
    )


BUILT_IN_MILESTONES: tuple[SelectionChoice, ...] = tuple(
    _seed("MilestoneSelection", *row, forAge=0, used="false") for row in _BUILT_IN_MILESTONES
)

BUILT_IN_VACCINES: tuple[SelectionChoice, ...] = tuple(
    _seed("VaccineSelection", *row, forAge=0) for row in _BUILT_IN_VACCINES
)


def choice_from_selection(selection: object, *, built_in: bool = False) -> SelectionChoice | None:
    """A choice for a selection object, or ``None`` without a string ID and name."""
    if not isinstance(selection, Mapping):
        return None
    object_id, name = selection.get("objectID"), selection.get("name")
    if not isinstance(object_id, str) or not object_id or not isinstance(name, str):
        return None
    return SelectionChoice(object_id, name, built_in, dict(selection))


def merged_choices(
    built_ins: Iterable[SelectionChoice],
    embedded: Iterable[object],
    synced: Iterable[object],
) -> list[SelectionChoice]:
    """The entries a record can name: the built-ins, in the app's order, then the rest by name.

    ``embedded`` are selection objects records already carry; ``synced`` are selections synced
    as records of their own. A copy of a built-in replaces its template (keeping it first), so
    a record embeds what the app has; a synced copy wins over an embedded one.
    """
    order = {choice.object_id: i for i, choice in enumerate(built_ins)}
    found: dict[str, SelectionChoice] = {}
    for built_in in built_ins:
        found[built_in.object_id] = built_in
    for source, overrides_added in ((embedded, False), (synced, True)):
        for selection in source:
            copy = choice_from_selection(selection)
            if copy is None:
                continue
            current = found.get(copy.object_id)
            if current is not None and not current.built_in and not overrides_added:
                continue
            found[copy.object_id] = SelectionChoice(
                copy.object_id, copy.name, copy.object_id in order, copy.selection
            )
    built = sorted((c for c in found.values() if c.built_in), key=lambda c: order[c.object_id])
    added = sorted((c for c in found.values() if not c.built_in), key=lambda c: c.name.casefold())
    return built + added


def find_choice(choices: Iterable[SelectionChoice], wanted: str) -> SelectionChoice | None:
    """The entry with that ID, or else that name, ignoring case and surrounding spaces."""
    listed = list(choices)
    key = wanted.strip().casefold()
    for choice in listed:
        if choice.object_id.casefold() == key:
            return choice
    for choice in listed:
        if choice.name.strip().casefold() == key:
            return choice
    return None

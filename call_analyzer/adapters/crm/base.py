"""What a CRM adapter does, and the shape of what it hands back.

The call desk works with contacts (people) and the opportunities attached to them, moved along a pipeline of
stages. Every CRM has these under some name (Twenty: people/opportunities, HubSpot: contacts/deals, Odoo:
partners/leads...). An adapter translates: it returns the dicts below and takes the ids it handed out.

To connect another CRM: subclass CrmAdapter in adapters/crm/<name>.py, add it to BUILTIN in crm.py (or call
crm.registry.register), then set CRM_PROVIDER=<name> in Settings. Caching, phone matching and the call desk's
rules stay in crm.py and operations.py: an adapter only talks to its CRM.
"""
from typing import TypedDict


class CrmError(Exception):
    """The CRM couldn't be queried or refused a change; the message is meant to be shown to the user."""


class Stage(TypedDict):
    value: str  # what the CRM stores (e.g. "NEW")
    label: str  # what people read (e.g. "New")


class Opportunity(TypedDict):
    id: str
    name: str
    stage: str | None  # a Stage value
    amount: float | None
    currency: str | None
    close_date: str | None
    company: str | None
    owner: str | None  # the owner's name
    created_at: str | None  # ISO 8601; the call queue serves the oldest first
    updated_at: str | None
    url: str | None  # the record in the CRM's web app


class Person(TypedDict, total=False):
    id: str
    name: str
    email: str | None
    phones: list[str]  # as the CRM shows them, e.g. "+216 22602716"
    job_title: str | None
    city: str | None
    company: str | None
    created_at: str | None
    last_contact_at: str | None
    url: str | None
    opportunities: list[Opportunity]  # only in find_people()


class Lead(Opportunity):
    contact: Person | None  # the opportunity's point of contact, without `opportunities`


class Note(TypedDict):
    id: str
    title: str
    text: str
    created_at: str | None
    author: str | None


class Member(TypedDict):
    id: str
    name: str
    email: str | None


class CrmAdapter:
    """One CRM. Settings are read when needed (config.live) so changes saved in Settings apply straight away.
    Every method that talks to the CRM raises CrmError when it can't."""

    name = ""  # what CRM_PROVIDER is set to
    label = ""  # shown to people, e.g. "Twenty"
    # Settings this adapter reads (from .env.example). Secret ones are masked on the Settings page.
    setting_keys: tuple[str, ...] = ()
    secret_keys: tuple[str, ...] = ()
    # The stage of opportunities nobody has worked on yet: the default call campaign calls these.
    lead_stage = "NEW"
    # The stage of opportunities we called but couldn't reach: they go at the end of the New leads queue.
    attempted_stage = "ATTEMPTED"

    def is_configured(self) -> bool:
        """Whether the settings it needs are filled in (no request is made)."""
        raise NotImplementedError

    def not_configured_message(self) -> str:
        """Tells an admin what to fill in, e.g. "add CRM_API_KEY in Settings"."""
        return f"set up {self.label or 'the CRM'} in Settings"

    # --- Reading -------------------------------------------------------------------------------

    def find_people(self, key: str) -> list[Person]:
        """Contacts with a phone number ending in `key` (phones.match_key), newest first, each with their
        opportunities."""
        raise NotImplementedError

    def list_opportunities(self, stage: str, oldest_first: bool, limit: int | None,
                           after: str | None = None) -> tuple[list[Lead], str | None]:
        """Up to `limit` opportunities (None: all of them, page after page) at `stage` with their contact, ordered by
        creation date, starting after the cursor `after` (None: from the first). Returns them and the cursor to read
        the next ones from, or None when the CRM holds no more. The cursor is whatever the CRM pages with (a
        string)."""
        raise NotImplementedError

    def get_opportunity(self, opportunity_id: str) -> Lead:
        raise NotImplementedError

    def stages(self) -> list[Stage]:
        """The opportunity pipeline, in order. Should fall back to a sensible list rather than raise."""
        raise NotImplementedError

    def notes(self, opportunity_id: str | None, person_id: str | None, limit: int) -> list[Note]:
        """Notes about this opportunity or person, newest first."""
        raise NotImplementedError

    def members(self) -> list[Member]:
        """The CRM's users, to link app accounts to (who owns the leads an agent adds)."""
        raise NotImplementedError

    # --- Writing -------------------------------------------------------------------------------

    def update_opportunity(self, opportunity_id: str, fields: dict) -> None:
        """`fields` uses the app's names: {"stage": <Stage value>}."""
        raise NotImplementedError

    def update_person(self, person_id: str, fields: dict) -> None:
        """`fields` are the CRM's own field names, as set on the campaign's questions (crm: "person.<field>")."""
        raise NotImplementedError

    def add_note(self, title: str, markdown: str, opportunity_id: str | None, person_id: str | None) -> str:
        """Write a note attached to the opportunity and/or the person; returns its id. `markdown` uses **bold** and
        one line per paragraph."""
        raise NotImplementedError

    def create_person(self, name: str, phone: str, city: str, email: str) -> dict:
        """Add a contact; returns at least {"id"}."""
        raise NotImplementedError

    def create_opportunity(self, name: str, person_id: str, stage: str, owner_id: str | None) -> dict:
        """Add an opportunity for a contact, owned by the member `owner_id`; returns at least {"id"}."""
        raise NotImplementedError

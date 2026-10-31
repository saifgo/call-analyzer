"""The built-in CRM: contacts, leads and notes kept in the app's own database (the crm_* tables in db.py).

It works with nothing to set up, so a team without a CRM can use the call desk straight away. Records get UUIDs like
an external CRM's, so the rest of the app treats them the same way. Besides the CrmAdapter methods, it has what the
app's own CRM screens need (searching and editing contacts, stages, custom fields).
"""
import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from ... import db
from ...phones import match_key
from .base import CrmAdapter, CrmError

# The usual pipeline for a new install. NEW and ATTEMPTED are locked: the call queue relies on them.
DEFAULT_STAGES = [("NEW", "New"), ("TO_CALL", "To Call"), ("ATTEMPTED", "Attempted"), ("IN_TALK", "In Talk"),
                  ("WAITING_REPLY", "Waiting Reply"), ("ACCEPTED", "Accepted"), ("ACCOUNT_MADE", "Account Made"),
                  ("INSTALLING", "Installing"), ("ACTIVE", "Active"), ("REJECTED", "Rejected")]
LOCKED_STAGES = ("NEW", "ATTEMPTED")
# Contact fields every contact has (columns of crm_people); anything else is a custom field (crm_fields).
BUILTIN_FIELDS = ("name", "email", "job_title", "city", "company")
FIELD_TYPES = ("text", "number", "boolean", "choice")
_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,39}$")
_TRUE = ("true", "1", "yes", "on")
_FALSE = ("false", "0", "no", "off", "")


def now() -> str:
    """UTC, ISO 8601 with milliseconds, like Twenty's dates (so imported and local records sort together)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def format_phone(number: str) -> str:
    """How a number is shown: Tunisian ones as "+216 XXXXXXXX", others as typed (digits and a leading +)."""
    cleaned = re.sub(r"[^\d+]", "", number or "")
    if re.fullmatch(r"(\+216|00216|216)?\d{8}", cleaned):
        return f"+216 {cleaned[-8:]}"
    return cleaned


@contextmanager
def _db():
    """A connection that commits when the block ends without an error, and is closed either way."""
    conn = db.connect()
    try:
        _seed(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _seed(conn) -> None:
    """A new database gets the usual stages, and a custom field for each contact field the default campaigns write."""
    if conn.execute("SELECT 1 FROM crm_stages LIMIT 1").fetchone():
        return
    for position, (value, label) in enumerate(DEFAULT_STAGES):
        conn.execute("INSERT INTO crm_stages (value, label, position, locked) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT DO NOTHING",
                     (value, label, position, int(value in LOCKED_STAGES)))
    from ... import campaigns  # here: campaigns imports crm, which loads this adapter
    seen = set(BUILTIN_FIELDS)
    for q in campaigns.DEFAULT_QUESTIONS + campaigns.INBOUND_QUESTIONS:
        key = str(q.get("crm") or "").removeprefix("person.")
        if not q.get("crm", "").startswith("person.") or key in seen or not _KEY_RE.match(key):
            continue
        seen.add(key)
        kind = {"boolean": "boolean", "number": "number", "select": "choice"}.get(q.get("type"), "text")
        options = json.dumps(q.get("options") or []) if kind == "choice" else None
        conn.execute("INSERT INTO crm_fields (key, label, type, options, position) VALUES (?, ?, ?, ?, ?) "
                     "ON CONFLICT DO NOTHING",
                     (key, q.get("label") or key, kind, options, len(seen)))
    conn.commit()


def _coerce(field: dict, value):
    """A custom field's value as stored, checked against its type. Raises CrmError."""
    if value is None or value == "":
        return None
    kind, label = field["type"], field["label"]
    if kind == "boolean":
        text = str(value).strip().lower()
        if isinstance(value, bool):
            return value
        if text in _TRUE or text in _FALSE:
            return text in _TRUE
        raise CrmError(f"\"{label}\" takes yes or no, not {value!r}.")
    if kind == "number":
        try:
            number = float(str(value).replace(",", ".").strip())
        except ValueError:
            raise CrmError(f"\"{label}\" takes a number, not {value!r}.") from None
        return int(number) if number.is_integer() else number
    if kind == "choice":
        choices = [str(o[0]) for o in json.loads(field["options"] or "[]")]
        if str(value) not in choices:
            raise CrmError(f"\"{label}\" must be one of: {', '.join(choices)}.")
        return str(value)
    return str(value).strip()


class InternalCrm(CrmAdapter):
    name = "internal"
    label = "Built-in CRM"
    local = True
    lead_stage = "NEW"
    attempted_stage = "ATTEMPTED"

    def is_configured(self) -> bool:
        return True

    def member_id(self, username: str, crm_member_id: str | None) -> str | None:
        return username  # its users are the app's accounts

    # --- Rows -> the app's shapes --------------------------------------------------------------

    @staticmethod
    def _phones(conn, person_ids: list[str]) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for start in range(0, len(person_ids), 500):
            chunk = person_ids[start:start + 500]
            for row in conn.execute(f"SELECT person_id, number FROM crm_phones WHERE person_id IN "
                                    f"({','.join('?' * len(chunk))}) ORDER BY person_id, position", chunk):
                found.setdefault(row["person_id"], []).append(row["number"])
        return found

    @staticmethod
    def _person(row, phones: list[str]) -> dict:
        return {
            "id": row["id"],
            "name": row["name"] or "Unnamed contact",
            "email": row["email"] or None,
            "phones": phones,
            "job_title": row["job_title"] or None,
            "city": row["city"] or None,
            "company": row["company"] or None,
            "created_at": row["created_at"],
            "last_contact_at": row["last_contact_at"],
            "url": f"#contacts/{row['id']}",
            "fields": json.loads(row["fields"] or "{}"),
            "source": row["source"],
        }

    @staticmethod
    def _opportunity(row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"] or "Untitled opportunity",
            "stage": row["stage"],
            "amount": row["amount"],
            "currency": row["currency"],
            "close_date": row["close_date"],
            "company": row["company"],
            "owner": row["owner_name"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "url": f"#contacts/{row['person_id']}?lead={row['id']}" if row["person_id"] else None,
        }

    _OPP_SQL = """SELECT o.*, p.company AS company, COALESCE(u.display_name, o.owner) AS owner_name
                  FROM crm_opportunities o LEFT JOIN crm_people p ON p.id = o.person_id
                  LEFT JOIN users u ON u.username = o.owner"""

    def _leads(self, conn, rows) -> list[dict]:
        person_ids = list({r["person_id"] for r in rows if r["person_id"]})
        people = {}
        if person_ids:
            phones = self._phones(conn, person_ids)
            for start in range(0, len(person_ids), 500):
                chunk = person_ids[start:start + 500]
                for p in conn.execute(f"SELECT * FROM crm_people WHERE id IN ({','.join('?' * len(chunk))})", chunk):
                    people[p["id"]] = self._person(p, phones.get(p["id"], []))
        return [{**self._opportunity(r), "contact": people.get(r["person_id"])} for r in rows]

    # --- Reading -------------------------------------------------------------------------------

    def find_people(self, key: str) -> list[dict]:
        with _db() as conn:
            rows = conn.execute("""SELECT * FROM crm_people WHERE id IN
                                   (SELECT person_id FROM crm_phones WHERE number_key = ?)
                                   ORDER BY created_at DESC LIMIT 20""", (key,)).fetchall()
            ids = [r["id"] for r in rows]
            phones = self._phones(conn, ids)
            by_person: dict[str, list[dict]] = {i: [] for i in ids}
            if ids:
                for r in conn.execute(f"{self._OPP_SQL} WHERE o.person_id IN ({','.join('?' * len(ids))}) "
                                      f"ORDER BY o.created_at DESC", ids):
                    by_person[r["person_id"]].append(self._opportunity(r))
            return [{**self._person(r, phones.get(r["id"], [])), "opportunities": by_person[r["id"]]} for r in rows]

    def list_opportunities(self, stage: str, oldest_first: bool, limit: int | None,
                           after: str | None = None) -> tuple[list[dict], str | None]:
        """Keyset paging on (created_at, id): the cursor is the last one's "created_at|id"."""
        op, order = (">", "ASC") if oldest_first else ("<", "DESC")
        sql, args = f"{self._OPP_SQL} WHERE o.stage = ?", [stage]
        if after:
            created, _, last_id = after.partition("|")
            sql += f" AND (o.created_at {op} ? OR (o.created_at = ? AND o.id {op} ?))"
            args += [created, created, last_id]
        sql += f" ORDER BY o.created_at {order}, o.id {order}"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit + 1)  # one more, to know whether there are others
        with _db() as conn:
            rows = conn.execute(sql, args).fetchall()
            more = limit is not None and len(rows) > limit
            rows = rows[:limit] if more else rows
            cursor = f"{rows[-1]['created_at']}|{rows[-1]['id']}" if more else None
            return self._leads(conn, rows), cursor

    def get_opportunity(self, opportunity_id: str) -> dict:
        with _db() as conn:
            row = conn.execute(f"{self._OPP_SQL} WHERE o.id = ?", (opportunity_id,)).fetchone()
            if not row:
                raise CrmError("That opportunity isn't in the CRM anymore.")
            return self._leads(conn, [row])[0]

    def stages(self) -> list[dict]:
        with _db() as conn:
            return [{"value": r["value"], "label": r["label"], "locked": bool(r["locked"])}
                    for r in conn.execute("SELECT * FROM crm_stages ORDER BY position, value")]

    def notes(self, opportunity_id: str | None, person_id: str | None, limit: int) -> list[dict]:
        clauses, args = [], []
        for column, value in (("opportunity_id", opportunity_id), ("person_id", person_id)):
            if value:
                clauses.append(f"n.{column} = ?")
                args.append(value)
        if not clauses:
            return []
        with _db() as conn:
            rows = conn.execute(f"""SELECT n.*, COALESCE(u.display_name, n.author) AS author_name FROM crm_notes n
                                    LEFT JOIN users u ON u.username = n.author WHERE {' OR '.join(clauses)}
                                    ORDER BY n.created_at DESC LIMIT ?""", args + [limit]).fetchall()
        return [{"id": r["id"], "title": r["title"], "text": r["body"], "created_at": r["created_at"],
                 "author": r["author_name"]} for r in rows]

    def members(self) -> list[dict]:
        with _db() as conn:
            rows = conn.execute("SELECT username, display_name FROM users").fetchall()
        members = [{"id": r["username"], "name": r["display_name"] or r["username"], "email": None} for r in rows]
        members.sort(key=lambda m: m["name"].lower())
        return members

    def fields(self) -> list[dict]:
        """The custom contact fields: [{key, label, type, options}], in order."""
        with _db() as conn:
            return [{"key": r["key"], "label": r["label"], "type": r["type"],
                     "options": json.loads(r["options"]) if r["options"] else None}
                    for r in conn.execute("SELECT * FROM crm_fields ORDER BY position, key")]

    # --- Writing -------------------------------------------------------------------------------

    def update_opportunity(self, opportunity_id: str, fields: dict) -> None:
        allowed = {"stage", "name", "amount", "currency", "close_date", "owner"}
        if unknown := set(fields) - allowed:
            raise CrmError(f"An opportunity has no {', '.join(sorted(unknown))}.")
        with _db() as conn:
            if "stage" in fields and not conn.execute("SELECT 1 FROM crm_stages WHERE value = ?",
                                                      (fields["stage"],)).fetchone():
                raise CrmError(f"There is no stage {fields['stage']!r} in the pipeline.")
            sets = ", ".join(f"{k} = ?" for k in fields)
            cur = conn.execute(f"UPDATE crm_opportunities SET {sets}, updated_at = ? WHERE id = ?",
                               [*fields.values(), now(), opportunity_id])
            if not cur.rowcount:
                raise CrmError("That opportunity isn't in the CRM anymore.")

    def update_person(self, person_id: str, fields: dict) -> None:
        """Built-in fields (name, email, job_title, city, company) and custom ones, by key."""
        with _db() as conn:
            self._update_person(conn, person_id, fields)

    @staticmethod
    def _update_person(conn, person_id: str, fields: dict) -> None:
        row = conn.execute("SELECT fields FROM crm_people WHERE id = ?", (person_id,)).fetchone()
        if not row:
            raise CrmError("That contact isn't in the CRM anymore.")
        custom = json.loads(row["fields"] or "{}")
        defined = {r["key"]: dict(r) for r in conn.execute("SELECT * FROM crm_fields")}
        columns = {}
        for key, value in fields.items():
            if key in BUILTIN_FIELDS:
                text = str(value or "").strip()
                if key == "name" and not text:
                    raise CrmError("A contact needs a name.")
                columns[key] = text or None
            elif key in defined:
                custom[key] = _coerce(defined[key], value)
            else:
                raise CrmError(f"Contacts have no field \"{key}\": an admin can add it in CRM setup.")
        columns["fields"] = json.dumps({k: v for k, v in custom.items() if v is not None}, ensure_ascii=False)
        sets = ", ".join(f"{k} = ?" for k in columns)
        conn.execute(f"UPDATE crm_people SET {sets}, updated_at = ? WHERE id = ?",
                     [*columns.values(), now(), person_id])

    def set_phones(self, person_id: str, numbers: list[str]) -> None:
        """Replace a contact's phone numbers (the first is the primary one)."""
        with _db() as conn:
            self._set_phones(conn, person_id, numbers)
            conn.execute("UPDATE crm_people SET updated_at = ? WHERE id = ?", (now(), person_id))

    @staticmethod
    def _set_phones(conn, person_id: str, numbers: list[str]) -> None:
        conn.execute("DELETE FROM crm_phones WHERE person_id = ?", (person_id,))
        shown = []
        for number in numbers:
            if (n := format_phone(number)) and n not in shown:
                shown.append(n)
        for position, number in enumerate(shown):
            conn.execute("INSERT INTO crm_phones (person_id, position, number, number_key) VALUES (?, ?, ?, ?)",
                         (person_id, position, number, match_key(number) or re.sub(r"\D", "", number)))

    def add_note(self, title: str, markdown: str, opportunity_id: str | None, person_id: str | None,
                 author: str | None = None) -> str:
        note_id = new_id()
        with _db() as conn:
            conn.execute("""INSERT INTO crm_notes (id, title, body, opportunity_id, person_id, author, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                         (note_id, title, markdown, opportunity_id, person_id, author, now()))
        return note_id

    def create_person(self, name: str, phone: str, city: str, email: str, source: str = "desk") -> dict:
        if not (name or "").strip():
            raise CrmError("A contact needs a name.")
        person_id, stamp = new_id(), now()
        with _db() as conn:
            conn.execute("""INSERT INTO crm_people (id, name, email, city, source, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                         (person_id, name.strip(), email.strip() or None, city.strip() or None, source, stamp, stamp))
            self._set_phones(conn, person_id, [phone] if phone else [])
        return {"id": person_id}

    def create_opportunity(self, name: str, person_id: str, stage: str, owner_id: str | None) -> dict:
        opportunity_id, stamp = new_id(), now()
        with _db() as conn:
            if not conn.execute("SELECT 1 FROM crm_people WHERE id = ?", (person_id,)).fetchone():
                raise CrmError("That contact isn't in the CRM anymore.")
            if not conn.execute("SELECT 1 FROM crm_stages WHERE value = ?", (stage,)).fetchone():
                raise CrmError(f"There is no stage {stage!r} in the pipeline.")
            conn.execute("""INSERT INTO crm_opportunities (id, name, person_id, stage, owner, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                         (opportunity_id, name.strip() or "Untitled opportunity", person_id, stage, owner_id, stamp,
                          stamp))
        return {"id": opportunity_id}

    # --- The app's own CRM screens (web/crm_api.py) --------------------------------------------

    def search_people(self, query: str = "", stage: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        """Contacts, newest first, whose name, email, city or company holds `query` (or a phone number its digits),
        and with `stage`, that have an opportunity at it. Returns {"people": [... with "opportunities"], "total"}."""
        clauses, args = [], []
        if text := query.strip().lower():
            like = f"%{text}%"
            match = ["LOWER(p.name) LIKE ?", "LOWER(COALESCE(p.email, '')) LIKE ?", "LOWER(COALESCE(p.city, '')) LIKE ?",
                     "LOWER(COALESCE(p.company, '')) LIKE ?"]
            args += [like] * len(match)
            if len(digits := re.sub(r"\D", "", text)) >= 3:
                match.append("p.id IN (SELECT person_id FROM crm_phones WHERE "
                             "REPLACE(REPLACE(REPLACE(number, ' ', ''), '+', ''), '-', '') LIKE ?)")
                args.append(f"%{digits}%")
            clauses.append(f"({' OR '.join(match)})")
        if stage:
            clauses.append("p.id IN (SELECT person_id FROM crm_opportunities WHERE stage = ?)")
            args.append(stage)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with _db() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM crm_people p {where}", args).fetchone()[0]
            rows = conn.execute(f"SELECT p.* FROM crm_people p {where} ORDER BY p.created_at DESC, p.id DESC "
                                f"LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
            return {"people": self._with_opportunities(conn, rows), "total": total}

    def _with_opportunities(self, conn, rows) -> list[dict]:
        ids = [r["id"] for r in rows]
        phones = self._phones(conn, ids)
        by_person: dict[str, list[dict]] = {i: [] for i in ids}
        if ids:
            for r in conn.execute(f"{self._OPP_SQL} WHERE o.person_id IN ({','.join('?' * len(ids))}) "
                                  f"ORDER BY o.created_at DESC", ids):
                by_person[r["person_id"]].append({**self._opportunity(r), "owner_id": r["owner"]})
        return [{**self._person(r, phones.get(r["id"], [])), "opportunities": by_person[r["id"]]} for r in rows]

    def get_person(self, person_id: str) -> dict:
        """A contact with their opportunities and every note about them or their opportunities, newest first."""
        with _db() as conn:
            row = conn.execute("SELECT * FROM crm_people WHERE id = ?", (person_id,)).fetchone()
            if not row:
                raise CrmError("That contact isn't in the CRM anymore.")
            person = self._with_opportunities(conn, [row])[0]
            rows = conn.execute("""SELECT n.*, COALESCE(u.display_name, n.author) AS author_name FROM crm_notes n
                                   LEFT JOIN users u ON u.username = n.author
                                   WHERE n.person_id = ? OR n.opportunity_id IN
                                         (SELECT id FROM crm_opportunities WHERE person_id = ?)
                                   ORDER BY n.created_at DESC LIMIT 200""", (person_id, person_id)).fetchall()
        person["notes"] = [{"id": r["id"], "title": r["title"], "text": r["body"], "created_at": r["created_at"],
                            "author": r["author_name"], "opportunity_id": r["opportunity_id"]} for r in rows]
        return person

    def create_contact(self, fields: dict, phones: list[str], source: str = "manual") -> dict:
        """Add a contact with any of its fields (built-in and custom, see update_person) and phone numbers."""
        if not str(fields.get("name") or "").strip():
            raise CrmError("A contact needs a name.")
        person_id, stamp = new_id(), now()
        with _db() as conn:
            conn.execute("""INSERT INTO crm_people (id, name, source, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?)""", (person_id, str(fields["name"]).strip(), source, stamp, stamp))
            self._update_person(conn, person_id, fields)
            self._set_phones(conn, person_id, phones)
        return {"id": person_id}

    @staticmethod
    def _refuse_if_on_desk(conn, where: str, args: list) -> None:
        busy = conn.execute(f"""SELECT COUNT(*) FROM op_calls WHERE {where}
                                AND status IN ('scheduled', 'assigned', 'in_call')""", args).fetchone()[0]
        if busy:
            raise CrmError("The call desk is still working on this (a call in progress or a callback booked): "
                           "finish or cancel it first.")

    def delete_person(self, person_id: str) -> None:
        """Remove a contact with their numbers, opportunities and notes."""
        with _db() as conn:
            self._refuse_if_on_desk(conn, "person_id = ? OR opportunity_id IN "
                                    "(SELECT id FROM crm_opportunities WHERE person_id = ?)", [person_id, person_id])
            conn.execute("DELETE FROM crm_notes WHERE person_id = ? OR opportunity_id IN "
                         "(SELECT id FROM crm_opportunities WHERE person_id = ?)", (person_id, person_id))
            conn.execute("DELETE FROM crm_opportunities WHERE person_id = ?", (person_id,))
            conn.execute("DELETE FROM crm_phones WHERE person_id = ?", (person_id,))
            if not conn.execute("DELETE FROM crm_people WHERE id = ?", (person_id,)).rowcount:
                raise CrmError("That contact isn't in the CRM anymore.")

    def delete_opportunity(self, opportunity_id: str) -> None:
        """Remove an opportunity. Its notes stay on the contact when they were written about them too."""
        with _db() as conn:
            self._refuse_if_on_desk(conn, "opportunity_id = ?", [opportunity_id])
            conn.execute("DELETE FROM crm_notes WHERE opportunity_id = ? AND person_id IS NULL", (opportunity_id,))
            conn.execute("UPDATE crm_notes SET opportunity_id = NULL WHERE opportunity_id = ?", (opportunity_id,))
            if not conn.execute("DELETE FROM crm_opportunities WHERE id = ?", (opportunity_id,)).rowcount:
                raise CrmError("That opportunity isn't in the CRM anymore.")

    def delete_note(self, note_id: str) -> None:
        with _db() as conn:
            if not conn.execute("DELETE FROM crm_notes WHERE id = ?", (note_id,)).rowcount:
                raise CrmError("That note isn't in the CRM anymore.")

    def stage_counts(self) -> dict[str, int]:
        with _db() as conn:
            return {r["stage"]: r["n"] for r in
                    conn.execute("SELECT stage, COUNT(*) AS n FROM crm_opportunities GROUP BY stage")}

    @staticmethod
    def campaign_uses(conn) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        """The campaigns using each stage (queue, outcomes, contacts that never answer) and each contact field."""
        stages: dict[str, list[str]] = {}
        fields: dict[str, list[str]] = {}
        for row in conn.execute("SELECT name, stages, outcomes, questions, exhausted_stage FROM op_campaigns"):
            used = set(json.loads(row["stages"] or "[]")) | {row["exhausted_stage"]}
            used |= {o.get("stage") for o in json.loads(row["outcomes"] or "[]")}
            for value in used - {None, ""}:
                stages.setdefault(value, []).append(row["name"])
            for q in json.loads(row["questions"] or "[]"):
                if str(q.get("crm") or "").startswith("person."):
                    fields.setdefault(q["crm"].removeprefix("person."), []).append(row["name"])
        return stages, fields

    def save_stages(self, stages: list[dict]) -> list[dict]:
        """Set the pipeline, in order: [{value (none for a new stage), label}]. A stage left out is removed, unless
        it's locked, an opportunity is at it, or a campaign uses it."""
        labels = [str(s.get("label") or "").strip() for s in stages]
        if not stages or any(not label for label in labels):
            raise CrmError("Every stage needs a name.")
        if len({label.lower() for label in labels}) < len(labels):
            raise CrmError("Two stages have the same name.")
        with _db() as conn:
            existing = {r["value"]: dict(r) for r in conn.execute("SELECT * FROM crm_stages")}
            kept = [str(s.get("value") or "") for s in stages if s.get("value")]
            if unknown := [v for v in kept if v not in existing]:
                raise CrmError(f"There is no stage {unknown[0]!r} in the pipeline.")
            removed = set(existing) - set(kept)
            counts = {r["stage"]: r["n"] for r in
                      conn.execute("SELECT stage, COUNT(*) AS n FROM crm_opportunities GROUP BY stage")}
            used, _ = self.campaign_uses(conn)
            for value in sorted(removed):
                label = existing[value]["label"]
                if existing[value]["locked"]:
                    raise CrmError(f"\"{label}\" can be renamed but not removed: the call queue relies on it.")
                if counts.get(value):
                    n = counts[value]
                    raise CrmError(f"\"{label}\" still has {n} {'opportunity' if n == 1 else 'opportunities'}: "
                                   "move them to another stage first.")
                if used.get(value):
                    raise CrmError(f"\"{label}\" is used by the campaign {', '.join(used[value])}: change the "
                                   "campaign first.")
            taken = set(existing)
            for value in removed:
                conn.execute("DELETE FROM crm_stages WHERE value = ?", (value,))
            for position, (stage, label) in enumerate(zip(stages, labels)):
                if value := stage.get("value"):
                    conn.execute("UPDATE crm_stages SET label = ?, position = ? WHERE value = ?",
                                 (label, position, value))
                    continue
                value = _new_key(label, taken, upper=True)
                taken.add(value)
                conn.execute("INSERT INTO crm_stages (value, label, position, locked) VALUES (?, ?, ?, 0)",
                             (value, label, position))
        return self.stages()

    def save_fields(self, fields: list[dict]) -> list[dict]:
        """Set the custom contact fields, in order: [{key (none for a new field), label, type, options}]; options
        (choice fields): their labels, or [value, label] pairs. A field left out is removed (the values contacts
        have for it are kept, in case it comes back), unless a campaign question writes to it."""
        labels = [str(f.get("label") or "").strip() for f in fields]
        if any(not label for label in labels):
            raise CrmError("Every field needs a name.")
        with _db() as conn:
            existing = {r["key"]: dict(r) for r in conn.execute("SELECT * FROM crm_fields")}
            kept = [str(f.get("key") or "") for f in fields if f.get("key")]
            if unknown := [k for k in kept if k not in existing]:
                raise CrmError(f"Contacts have no field {unknown[0]!r}.")
            _, used = self.campaign_uses(conn)
            removed = set(existing) - set(kept)
            for key in sorted(removed):
                if used.get(key):
                    raise CrmError(f"\"{existing[key]['label']}\" is filled in by the campaign "
                                   f"{', '.join(used[key])}: change its questions first.")
            rows = []
            taken = set(existing) | set(BUILTIN_FIELDS)
            for field, label in zip(fields, labels):
                kind = field.get("type") or "text"
                if kind not in FIELD_TYPES:
                    raise CrmError(f"\"{label}\": a field is {', '.join(FIELD_TYPES)}, not {kind!r}.")
                options = None
                if kind == "choice":
                    pairs, seen = [], set()
                    for option in field.get("options") or []:
                        value, text = (option[0], option[1]) if isinstance(option, (list, tuple)) else (None, option)
                        text = str(text or "").strip()
                        if not text:
                            continue
                        value = str(value or "").strip() or _new_key(text, seen)
                        seen.add(value)
                        pairs.append([value, text])
                    if not pairs:
                        raise CrmError(f"\"{label}\" needs at least one choice.")
                    options = json.dumps(pairs, ensure_ascii=False)
                key = field.get("key") or _new_key(label, taken)
                taken.add(key)
                rows.append((key, label, kind, options))
            for key in removed:
                conn.execute("DELETE FROM crm_fields WHERE key = ?", (key,))
            for position, (key, label, kind, options) in enumerate(rows):
                if key in existing:
                    conn.execute("UPDATE crm_fields SET label = ?, type = ?, options = ?, position = ? WHERE key = ?",
                                 (label, kind, options, position, key))
                else:
                    conn.execute("INSERT INTO crm_fields (key, label, type, options, position) VALUES (?, ?, ?, ?, ?)",
                                 (key, label, kind, options, position))
        return self.fields()


def _new_key(label: str, taken: set[str], upper: bool = False) -> str:
    """A key for a new stage (IN_TALK) or field (shop_type) named `label`, not in `taken`."""
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:30]
    if not base or not base[0].isalpha():
        base = f"{'stage' if upper else 'field'}_{base}".rstrip("_")
    base = base.upper() if upper else base
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    return key

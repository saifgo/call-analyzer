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
        conn.execute("INSERT OR IGNORE INTO crm_stages (value, label, position, locked) VALUES (?, ?, ?, ?)",
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
        conn.execute("INSERT OR IGNORE INTO crm_fields (key, label, type, options, position) VALUES (?, ?, ?, ?, ?)",
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
                    raise CrmError(f"Contacts have no field \"{key}\": an admin can add it in Settings > CRM.")
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

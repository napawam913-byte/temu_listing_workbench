from __future__ import annotations

import os
import secrets
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional runtime dependency
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

from app.core.database import (
    admin_public_user,
    clean_text,
    default_team_id,
    hash_password,
    normalize_user_role,
    normalize_user_status,
    public_user,
    session_expiry_cutoff_text,
    utc_now_text,
    verify_password,
)
from app.core.postgres_pool import get_postgres_connection

_identity_schema_ready = False
_identity_schema_lock = Lock()
SESSION_TOUCH_INTERVAL_SECONDS = 300


def is_enabled() -> bool:
    return True


def configured_url() -> str:
    return (
        os.getenv("IDENTITY_DATABASE_URL", "").strip()
        or os.getenv("POSTGRES_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )


@contextmanager
def get_pg_connection() -> Iterator[Any]:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed; run python -m pip install -r requirements.txt")
    url = configured_url()
    if not url:
        raise RuntimeError("Identity PostgreSQL backend requires IDENTITY_DATABASE_URL, POSTGRES_DATABASE_URL, or DATABASE_URL")
    with get_postgres_connection(url) as conn:
        yield conn


def ensure_identity_schema(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            manager_user_id TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_seen_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            admin_user_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_members (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            member_role TEXT NOT NULL DEFAULT 'member',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id, status)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_admin_unique ON teams(admin_user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_teams_admin ON teams(admin_user_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_team_members_team_user ON team_members(team_id, user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_team_members_user ON team_members(user_id)")


def ensure_identity_schema_ready() -> None:
    global _identity_schema_ready
    if _identity_schema_ready:
        return
    with _identity_schema_lock:
        if _identity_schema_ready:
            return
        with get_pg_connection() as conn:
            ensure_identity_schema(conn)
        _identity_schema_ready = True


def pg_table_exists(conn: Any, table_name: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s) AS table_name", (f"public.{table_name}",)).fetchone()
    return bool(row and row["table_name"])


def sync_user_teams(conn: Any) -> None:
    now = utc_now_text()
    admins = conn.execute(
        "SELECT id, username, display_name FROM users WHERE role = 'admin' ORDER BY created_at ASC"
    ).fetchall()
    for admin in admins:
        team_id = default_team_id(admin["id"])
        team_name = f"{admin['display_name'] or admin['username']} 的团队"
        conn.execute(
            """
            INSERT INTO teams (id, name, admin_user_id, status, created_at, updated_at)
            VALUES (%s, %s, %s, 'active', %s, %s)
            ON CONFLICT (admin_user_id) DO UPDATE SET
                name = EXCLUDED.name,
                status = 'active',
                updated_at = EXCLUDED.updated_at
            """,
            (team_id, team_name, admin["id"], now, now),
        )
        conn.execute(
            """
            INSERT INTO team_members (id, team_id, user_id, member_role, created_at, updated_at)
            VALUES (%s, %s, %s, 'admin', %s, %s)
            ON CONFLICT (team_id, user_id) DO UPDATE SET
                member_role = 'admin',
                updated_at = EXCLUDED.updated_at
            """,
            (uuid.uuid4().hex, team_id, admin["id"], now, now),
        )

    rows = conn.execute(
        """
        SELECT users.id, users.manager_user_id, teams.id AS team_id
        FROM users
        JOIN teams ON teams.admin_user_id = users.manager_user_id
        WHERE users.manager_user_id IS NOT NULL AND users.manager_user_id != ''
        """
    ).fetchall()
    conn.execute("DELETE FROM team_members WHERE member_role = 'member'")
    for row in rows:
        conn.execute(
            """
            INSERT INTO team_members (id, team_id, user_id, member_role, created_at, updated_at)
            VALUES (%s, %s, %s, 'member', %s, %s)
            ON CONFLICT (team_id, user_id) DO UPDATE SET
                member_role = 'member',
                updated_at = EXCLUDED.updated_at
            """,
            (uuid.uuid4().hex, row["team_id"], row["id"], now, now),
        )


def create_user(username: str, password: str, display_name: str | None = None) -> dict[str, Any]:
    ensure_identity_schema_ready()
    clean_username = " ".join(str(username or "").split()).strip()
    if len(clean_username) < 2:
        raise ValueError("用户名至少需要 2 个字符")
    if len(str(password or "")) < 6:
        raise ValueError("密码至少需要 6 个字符")

    salt, password_hash = hash_password(password)
    now = utc_now_text()
    user_id = uuid.uuid4().hex
    try:
        with get_pg_connection() as conn:
            row = conn.execute(
                """
                INSERT INTO users (
                    id, username, display_name, password_hash, password_salt, role, status, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, 'user', 'active', %s, %s)
                RETURNING *
                """,
                (
                    user_id,
                    clean_username,
                    " ".join(str(display_name or clean_username).split()).strip(),
                    password_hash,
                    salt,
                    now,
                    now,
                ),
            ).fetchone()
    except Exception as exc:
        if psycopg is not None and isinstance(exc, psycopg.IntegrityError):
            raise ValueError("用户名已存在") from exc
        raise

    return public_user(row)


def list_users() -> list[dict[str, Any]]:
    ensure_identity_schema_ready()
    with get_pg_connection() as conn:
        sync_user_teams(conn)
        expire_stale_user_sessions(conn)
        rows = conn.execute(
            """
            WITH active_sessions AS (
                SELECT user_id, COUNT(*) AS active_session_count
                FROM user_sessions
                WHERE status = 'active'
                GROUP BY user_id
            )
            SELECT
                users.*,
                manager.username AS manager_username,
                manager.display_name AS manager_display_name,
                teams.id AS team_id,
                teams.name AS team_name,
                COALESCE(active_sessions.active_session_count, 0) AS active_session_count
            FROM users
            LEFT JOIN active_sessions ON active_sessions.user_id = users.id
            LEFT JOIN users AS manager ON manager.id = users.manager_user_id
            LEFT JOIN teams ON teams.admin_user_id = users.manager_user_id
            ORDER BY users.created_at ASC
            """
        ).fetchall()
    return [admin_public_user(row) for row in rows]


def create_managed_user(
    *,
    username: str,
    password: str,
    display_name: str | None = None,
    role: str = "user",
    status: str = "active",
    manager_user_id: str | None = None,
) -> dict[str, Any]:
    ensure_identity_schema_ready()
    clean_username = " ".join(str(username or "").split()).strip()
    if len(clean_username) < 2:
        raise ValueError("用户名至少需要 2 个字符")
    if len(str(password or "")) < 6:
        raise ValueError("密码至少需要 6 个字符")
    clean_role = normalize_user_role(role)
    clean_status = normalize_user_status(status)

    salt, password_hash = hash_password(password)
    now = utc_now_text()
    user_id = uuid.uuid4().hex
    try:
        with get_pg_connection() as conn:
            clean_manager_user_id = resolve_manager_user_id(conn, manager_user_id, role=clean_role)
            conn.execute(
                """
                INSERT INTO users (
                    id, username, display_name, password_hash, password_salt, role, manager_user_id, status, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    clean_username,
                    " ".join(str(display_name or clean_username).split()).strip(),
                    password_hash,
                    salt,
                    clean_role,
                    clean_manager_user_id,
                    clean_status,
                    now,
                    now,
                ),
            )
            sync_user_teams(conn)
            row = fetch_admin_user_row(conn, user_id)
    except Exception as exc:
        if psycopg is not None and isinstance(exc, psycopg.IntegrityError):
            raise ValueError("用户名已存在") from exc
        raise

    return admin_public_user(row)


def update_managed_user(
    user_id: str,
    *,
    display_name: str | None = None,
    role: str | None = None,
    status: str | None = None,
    manager_user_id: str | None = None,
) -> dict[str, Any]:
    ensure_identity_schema_ready()
    clean_user_id = str(user_id or "").strip()
    if not clean_user_id:
        raise ValueError("缺少用户 ID")

    updates: list[str] = []
    params: list[Any] = []
    if display_name is not None:
        updates.append("display_name = %s")
        params.append(" ".join(str(display_name).split()).strip())
    if role is not None:
        updates.append("role = %s")
        params.append(normalize_user_role(role))
    if status is not None:
        updates.append("status = %s")
        params.append(normalize_user_status(status))

    manager_update_requested = manager_user_id is not None
    with get_pg_connection() as conn:
        existing = conn.execute("SELECT * FROM users WHERE id = %s", (clean_user_id,)).fetchone()
        if not existing:
            raise ValueError("用户不存在")
        if not updates and not manager_update_requested:
            row = fetch_admin_user_row(conn, clean_user_id)
            return admin_public_user(row)

        next_role = normalize_user_role(role) if role is not None else existing["role"]
        next_status = normalize_user_status(status) if status is not None else existing["status"]
        if manager_update_requested or (role is not None and next_role == "admin"):
            clean_manager_user_id = resolve_manager_user_id(
                conn,
                manager_user_id,
                role=next_role,
                user_id=clean_user_id,
            )
            updates.append("manager_user_id = %s")
            params.append(clean_manager_user_id)
        if existing["role"] == "admin" and (next_role != "admin" or next_status != "active"):
            active_admin_count = conn.execute(
                "SELECT COUNT(*) AS count FROM users WHERE role = 'admin' AND status = 'active'"
            ).fetchone()["count"]
            if int(active_admin_count or 0) <= 1:
                raise ValueError("至少需要保留一个启用中的管理员")

        now = utc_now_text()
        updates.append("updated_at = %s")
        params.append(now)
        params.append(clean_user_id)
        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = %s", params)
        sync_user_teams(conn)
        if status is not None and next_status != "active":
            conn.execute(
                "UPDATE user_sessions SET status = 'revoked', updated_at = %s WHERE user_id = %s AND status = 'active'",
                (now, clean_user_id),
            )
        row = fetch_admin_user_row(conn, clean_user_id)
    return admin_public_user(row)


def delete_managed_users(user_ids: list[str], *, requested_by_user_id: str) -> dict[str, Any]:
    ensure_identity_schema_ready()
    clean_ids = []
    seen: set[str] = set()
    for user_id in user_ids:
        clean_user_id = clean_text(user_id)
        if clean_user_id and clean_user_id not in seen:
            seen.add(clean_user_id)
            clean_ids.append(clean_user_id)
    if not clean_ids:
        raise ValueError("请选择要删除的成员")

    requester_id = clean_text(requested_by_user_id)
    if requester_id in seen:
        raise ValueError("不能删除当前登录的管理员账号")

    with get_pg_connection() as conn:
        rows = conn.execute(
            "SELECT id, username, role, status FROM users WHERE id = ANY(%s)",
            (clean_ids,),
        ).fetchall()
        found_ids = {row["id"] for row in rows}
        missing_ids = [user_id for user_id in clean_ids if user_id not in found_ids]
        if missing_ids:
            raise ValueError(f"成员不存在：{', '.join(missing_ids)}")

        deleting_admin_ids = [row["id"] for row in rows if row["role"] == "admin"]
        if deleting_admin_ids:
            active_admin_count = conn.execute(
                "SELECT COUNT(*) AS count FROM users WHERE role = 'admin' AND status = 'active'"
            ).fetchone()["count"]
            deleting_active_admin_count = sum(1 for row in rows if row["role"] == "admin" and row["status"] == "active")
            if int(active_admin_count or 0) - deleting_active_admin_count <= 0:
                raise ValueError("至少需要保留一个启用中的管理员")

        now = utc_now_text()
        remaining_admin = conn.execute(
            """
            SELECT id
            FROM users
            WHERE id = %s AND role = 'admin' AND status = 'active'
            """,
            (requester_id,),
        ).fetchone()
        fallback_manager_id = requester_id if remaining_admin else ""

        if fallback_manager_id:
            conn.execute(
                """
                UPDATE users
                SET manager_user_id = %s, updated_at = %s
                WHERE manager_user_id = ANY(%s)
                  AND NOT (id = ANY(%s))
                """,
                (fallback_manager_id, now, deleting_admin_ids, clean_ids),
            )
        elif deleting_admin_ids:
            conn.execute(
                """
                UPDATE users
                SET manager_user_id = '', updated_at = %s
                WHERE manager_user_id = ANY(%s)
                  AND NOT (id = ANY(%s))
                """,
                (now, deleting_admin_ids, clean_ids),
            )

        cleanup_tables = (
            ("user_sessions", "user_id"),
            ("team_members", "user_id"),
            ("user_api_settings", "user_id"),
            ("user_usage_limits", "user_id"),
            ("api_usage_logs", "user_id"),
            ("product_pool_memberships", "user_id"),
        )
        for table_name, column_name in cleanup_tables:
            if pg_table_exists(conn, table_name):
                conn.execute(
                    f"DELETE FROM {table_name} WHERE {column_name} = ANY(%s)",
                    (clean_ids,),
                )

        if deleting_admin_ids and pg_table_exists(conn, "teams"):
            conn.execute("DELETE FROM teams WHERE admin_user_id = ANY(%s)", (deleting_admin_ids,))

        if pg_table_exists(conn, "app_settings"):
            conn.execute(
                "UPDATE app_settings SET updated_by = NULL WHERE updated_by = ANY(%s)",
                (clean_ids,),
            )

        deleted_rows = conn.execute(
            "DELETE FROM users WHERE id = ANY(%s)",
            (clean_ids,),
        ).rowcount
        sync_user_teams(conn)

    return {"deletedCount": int(deleted_rows or 0), "deletedIds": clean_ids}


def reset_managed_user_password(user_id: str, password: str) -> dict[str, Any]:
    ensure_identity_schema_ready()
    clean_user_id = str(user_id or "").strip()
    if len(str(password or "")) < 6:
        raise ValueError("密码至少需要 6 个字符")

    salt, password_hash = hash_password(password)
    now = utc_now_text()
    with get_pg_connection() as conn:
        existing = conn.execute("SELECT id FROM users WHERE id = %s", (clean_user_id,)).fetchone()
        if not existing:
            raise ValueError("用户不存在")
        conn.execute(
            """
            UPDATE users
            SET password_salt = %s, password_hash = %s, updated_at = %s
            WHERE id = %s
            """,
            (salt, password_hash, now, clean_user_id),
        )
        conn.execute(
            "UPDATE user_sessions SET status = 'revoked', updated_at = %s WHERE user_id = %s AND status = 'active'",
            (now, clean_user_id),
        )
        row = fetch_admin_user_row(conn, clean_user_id)
    return admin_public_user(row)


def fetch_admin_user_row(conn: Any, user_id: str) -> dict[str, Any] | None:
    sync_user_teams(conn)
    expire_stale_user_sessions(conn)
    return conn.execute(
        """
        WITH active_sessions AS (
            SELECT user_id, COUNT(*) AS active_session_count
            FROM user_sessions
            WHERE status = 'active'
            GROUP BY user_id
        )
        SELECT
            users.*,
            manager.username AS manager_username,
            manager.display_name AS manager_display_name,
            teams.id AS team_id,
            teams.name AS team_name,
            COALESCE(active_sessions.active_session_count, 0) AS active_session_count
        FROM users
        LEFT JOIN active_sessions ON active_sessions.user_id = users.id
        LEFT JOIN users AS manager ON manager.id = users.manager_user_id
        LEFT JOIN teams ON teams.admin_user_id = users.manager_user_id
        WHERE users.id = %s
        """,
        (user_id,),
    ).fetchone()


def resolve_manager_user_id(
    conn: Any,
    manager_user_id: str | None,
    *,
    role: str,
    user_id: str | None = None,
) -> str:
    if role == "admin":
        return ""
    clean_manager_user_id = clean_text(manager_user_id)
    if not clean_manager_user_id:
        return ""
    if clean_manager_user_id == clean_text(user_id):
        raise ValueError("成员不能归属到自己")
    row = conn.execute(
        "SELECT id FROM users WHERE id = %s AND role = 'admin' AND status = 'active'",
        (clean_manager_user_id,),
    ).fetchone()
    if not row:
        raise ValueError("归属管理员不存在或未启用")
    return clean_manager_user_id


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    ensure_identity_schema_ready()
    clean_username = " ".join(str(username or "").split()).strip()
    with get_pg_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = %s AND status = 'active'",
            (clean_username,),
        ).fetchone()
    if not row:
        return None
    if not verify_password(password, salt=row["password_salt"], password_hash=row["password_hash"]):
        return None
    return public_user(row)


def expire_stale_user_sessions(conn: Any | None = None) -> int:
    if conn is None:
        ensure_identity_schema_ready()
    cutoff = session_expiry_cutoff_text()
    now = utc_now_text()

    def update(target_conn: Any) -> int:
        cursor = target_conn.execute(
            """
            WITH stale_sessions AS (
                SELECT token
                FROM user_sessions
                WHERE status = 'active'
                  AND COALESCE(last_seen_at, updated_at, created_at) < %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE user_sessions
            SET status = 'expired', updated_at = %s
            FROM stale_sessions
            WHERE user_sessions.token = stale_sessions.token
            """,
            (cutoff, now),
        )
        return cursor.rowcount

    if conn is not None:
        return update(conn)

    with get_pg_connection() as owned_conn:
        return update(owned_conn)


def session_touch_cutoff_text() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(tzinfo=None, microsecond=0)
        - timedelta(seconds=SESSION_TOUCH_INTERVAL_SECONDS)
    ).isoformat(sep=" ")


def create_user_session(user_id: str) -> dict[str, Any]:
    ensure_identity_schema_ready()
    token = secrets.token_urlsafe(32)
    now = utc_now_text()
    with get_pg_connection() as conn:
        expire_stale_user_sessions(conn)
        user_row = conn.execute(
            "SELECT * FROM users WHERE id = %s AND status = 'active'",
            (user_id,),
        ).fetchone()
        if not user_row:
            raise ValueError("用户不存在或已停用")
        conn.execute(
            """
            INSERT INTO user_sessions (token, user_id, status, created_at, updated_at, last_seen_at)
            VALUES (%s, %s, 'active', %s, %s, %s)
            """,
            (token, user_id, now, now, now),
        )
    return {"token": token, "user": public_user(user_row)}


def get_user_by_session_token(token: str) -> dict[str, Any] | None:
    ensure_identity_schema_ready()
    clean_token = str(token or "").strip()
    if not clean_token:
        return None

    now = utc_now_text()
    cutoff = session_expiry_cutoff_text()
    with get_pg_connection() as conn:
        row = conn.execute(
            """
            SELECT users.*
            FROM user_sessions
            JOIN users ON users.id = user_sessions.user_id
            WHERE user_sessions.token = %s
                AND user_sessions.status = 'active'
                AND users.status = 'active'
                AND COALESCE(user_sessions.last_seen_at, user_sessions.updated_at, user_sessions.created_at) >= %s
            """,
            (clean_token, cutoff),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE user_sessions
                SET last_seen_at = %s, updated_at = %s
                WHERE token = %s
                  AND (
                      last_seen_at IS NULL
                      OR last_seen_at < %s
                  )
                """,
                (now, now, clean_token, session_touch_cutoff_text()),
            )
        else:
            conn.execute(
                """
                UPDATE user_sessions
                SET status = 'expired', updated_at = %s
                WHERE token = %s
                    AND status = 'active'
                    AND COALESCE(last_seen_at, updated_at, created_at) < %s
                """,
                (now, clean_token, cutoff),
            )
    return public_user(row) if row else None


def revoke_user_session(token: str) -> bool:
    ensure_identity_schema_ready()
    clean_token = str(token or "").strip()
    if not clean_token:
        return False
    now = utc_now_text()
    with get_pg_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE user_sessions
            SET status = 'revoked', updated_at = %s
            WHERE token = %s AND status = 'active'
            """,
            (now, clean_token),
        )
    return cursor.rowcount > 0

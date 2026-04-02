"""Create and maintain separate Neon runtime and migrator roles."""

from __future__ import annotations

import argparse
import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from psycopg import connect as pg_connect


ROLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _require_role_name(value: str) -> str:
    if not ROLE_NAME_RE.match(value):
        raise ValueError(f"Invalid Postgres role name: {value}")
    return value


def _quote_literal(value: str) -> str:
    return value.replace("'", "''")


def _replace_credentials(database_url: str, username: str, password: str) -> str:
    parsed = urlsplit(database_url)
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{hostname}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _execute(admin_url: str, statements: list[str]) -> None:
    with pg_connect(admin_url, autocommit=True) as conn, conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)


def _build_role_sql(
    *,
    database_name: str,
    owner_role: str,
    app_role: str,
    app_password: str,
    worker_role: str,
    worker_password: str,
    migrator_role: str,
    migrator_password: str,
) -> list[str]:
    app_role = _require_role_name(app_role)
    worker_role = _require_role_name(worker_role)
    migrator_role = _require_role_name(migrator_role)
    owner_role = _require_role_name(owner_role)

    app_password_sql = _quote_literal(app_password)
    worker_password_sql = _quote_literal(worker_password)
    migrator_password_sql = _quote_literal(migrator_password)

    runtime_grants = [
        f"GRANT CONNECT ON DATABASE {database_name} TO {app_role}, {worker_role}, {migrator_role};",
        f"GRANT CREATE ON DATABASE {database_name} TO {migrator_role};",
        f"GRANT {migrator_role} TO {owner_role};",
    ]

    schema_grants = [
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'public') THEN
            GRANT USAGE, CREATE ON SCHEMA public TO {migrator_role};
          END IF;
        END
        $$;
        """,
        f"""
        DO $$
        DECLARE
          schema_name text;
          object_table_name text;
          object_materialized_view_name text;
          object_sequence_name text;
          object_function_name text;
        BEGIN
          FOREACH schema_name IN ARRAY ARRAY['authn', 'app', 'ops']
          LOOP
            IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = schema_name) THEN
              EXECUTE format('ALTER SCHEMA %I OWNER TO {migrator_role}', schema_name);

              FOR object_table_name IN
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = schema_name
              LOOP
                EXECUTE format(
                  'ALTER TABLE %I.%I OWNER TO {migrator_role}',
                  schema_name,
                  object_table_name
                );
              END LOOP;

              FOR object_materialized_view_name IN
                SELECT matviewname
                FROM pg_matviews
                WHERE schemaname = schema_name
              LOOP
                EXECUTE format(
                  'ALTER MATERIALIZED VIEW %I.%I OWNER TO {migrator_role}',
                  schema_name,
                  object_materialized_view_name
                );
              END LOOP;

              FOR object_sequence_name IN
                SELECT sequence_name
                FROM information_schema.sequences
                WHERE sequence_schema = schema_name
              LOOP
                EXECUTE format(
                  'ALTER SEQUENCE %I.%I OWNER TO {migrator_role}',
                  schema_name,
                  object_sequence_name
                );
              END LOOP;

              FOR object_function_name IN
                SELECT p.oid::regprocedure::text
                FROM pg_proc p
                INNER JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = schema_name
              LOOP
                EXECUTE format('ALTER FUNCTION %s OWNER TO {migrator_role}', object_function_name);
              END LOOP;
            END IF;
          END LOOP;
        END
        $$;
        """,
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'authn') THEN
            GRANT USAGE ON SCHEMA authn TO {app_role};
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA authn TO {app_role};
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA authn TO {app_role};
            GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA authn TO {app_role};
          END IF;
        END
        $$;
        """,
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'app') THEN
            GRANT USAGE ON SCHEMA app TO {app_role}, {worker_role};
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO {app_role};
            GRANT SELECT ON ALL TABLES IN SCHEMA app TO {worker_role};
            GRANT MAINTAIN ON ALL TABLES IN SCHEMA app TO {worker_role};
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO {app_role}, {worker_role};
            GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO {app_role};
          END IF;
        END
        $$;
        """,
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'ops') THEN
            GRANT USAGE ON SCHEMA ops TO {app_role}, {worker_role};
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ops TO {app_role}, {worker_role};
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ops TO {app_role}, {worker_role};
            GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ops TO {app_role}, {worker_role};
          END IF;
        END
        $$;
        """,
    ]

    default_privileges = []
    for grantor in (owner_role, migrator_role):
        default_privileges.extend(
            [
                f"""
                DO $$
                BEGIN
                  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'authn') THEN
                    ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA authn
                      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app_role};
                    ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA authn
                      GRANT USAGE, SELECT ON SEQUENCES TO {app_role};
                    ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA authn
                      GRANT EXECUTE ON FUNCTIONS TO {app_role};
                  END IF;
                END
                $$;
                """,
                f"""
                DO $$
                BEGIN
                  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'app') THEN
                    ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA app
                      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app_role};
                    ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA app
                      GRANT SELECT ON TABLES TO {worker_role};
                    ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA app
                      GRANT MAINTAIN ON TABLES TO {worker_role};
                    ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA app
                      GRANT USAGE, SELECT ON SEQUENCES TO {app_role}, {worker_role};
                    ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA app
                      GRANT EXECUTE ON FUNCTIONS TO {app_role};
                  END IF;
                END
                $$;
                """,
                f"""
                DO $$
                BEGIN
                  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'ops') THEN
                    ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA ops
                      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app_role}, {worker_role};
                    ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA ops
                      GRANT USAGE, SELECT ON SEQUENCES TO {app_role}, {worker_role};
                    ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA ops
                      GRANT EXECUTE ON FUNCTIONS TO {app_role}, {worker_role};
                  END IF;
                END
                $$;
                """,
            ]
        )

    return [
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{app_role}') THEN
            CREATE ROLE {app_role} LOGIN PASSWORD '{app_password_sql}';
          ELSE
            ALTER ROLE {app_role} LOGIN PASSWORD '{app_password_sql}';
          END IF;
        END
        $$;
        """,
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{worker_role}') THEN
            CREATE ROLE {worker_role} LOGIN PASSWORD '{worker_password_sql}';
          ELSE
            ALTER ROLE {worker_role} LOGIN PASSWORD '{worker_password_sql}';
          END IF;
        END
        $$;
        """,
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{migrator_role}') THEN
            CREATE ROLE {migrator_role} LOGIN PASSWORD '{migrator_password_sql}';
          ELSE
            ALTER ROLE {migrator_role} LOGIN PASSWORD '{migrator_password_sql}';
          END IF;
        END
        $$;
        """,
        *runtime_grants,
        *schema_grants,
        *default_privileges,
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create/update Neon runtime and migrator roles")
    parser.add_argument("--admin-url", required=True)
    parser.add_argument("--app-role", default="set_list_app")
    parser.add_argument("--app-password", required=True)
    parser.add_argument("--worker-role", default="set_list_worker")
    parser.add_argument("--worker-password", required=True)
    parser.add_argument("--migrator-role", default="set_list_migrator")
    parser.add_argument("--migrator-password", required=True)
    args = parser.parse_args()

    parsed = urlsplit(args.admin_url)
    owner_role = unquote(parsed.username or "")
    database_name = parsed.path.lstrip("/")
    if not owner_role:
        raise SystemExit("Admin URL must include a username")
    if not database_name:
        raise SystemExit("Admin URL must include a database name")

    statements = _build_role_sql(
        database_name=_require_role_name(database_name),
        owner_role=owner_role,
        app_role=args.app_role,
        app_password=args.app_password,
        worker_role=args.worker_role,
        worker_password=args.worker_password,
        migrator_role=args.migrator_role,
        migrator_password=args.migrator_password,
    )
    _execute(args.admin_url, statements)

    print(f"APP_DATABASE_URL={_replace_credentials(args.admin_url, args.app_role, args.app_password)}")
    print(f"WORKER_DATABASE_URL={_replace_credentials(args.admin_url, args.worker_role, args.worker_password)}")
    print(
        f"MIGRATOR_DATABASE_URL="
        f"{_replace_credentials(args.admin_url, args.migrator_role, args.migrator_password)}"
    )


if __name__ == "__main__":
    main()

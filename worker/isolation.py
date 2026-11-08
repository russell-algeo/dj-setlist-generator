"""Reject accidental development worker connections to another database.

These checks complement database credentials and platform secret isolation.
They cannot constrain someone who can replace the workflow or Python code.
"""

import os
from urllib.parse import parse_qsl, unquote, urlsplit


DEVELOPMENT_DATABASE_HOST = "ep-autumn-bar-a4f9xp8v.us-east-1.aws.neon.tech"
DEVELOPMENT_DATABASE_ROLE = "set_list_dev_worker"


def validate_database_target(database_url: str) -> None:
    if os.getenv("WORKER_DEPLOYMENT_TARGET") != "development":
        return
    try:
        url = urlsplit(database_url)
        query = parse_qsl(url.query, keep_blank_values=True)
        valid = (
            url.scheme in {"postgres", "postgresql"}
            and url.hostname == DEVELOPMENT_DATABASE_HOST
            and unquote(url.username or "") == DEVELOPMENT_DATABASE_ROLE
            and url.path == "/neondb"
            and url.port in {None, 5432}
            and not url.fragment
            and all(key in {"sslmode", "channel_binding", "connect_timeout"}
                    for key, _ in query)
            and any(key == "sslmode" for key, _ in query)
            and all(value in {"require", "verify-ca", "verify-full"}
                    for key, value in query if key == "sslmode")
            and not any(os.getenv(key) for key in
                        ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"))
        )
    except ValueError:
        valid = False
    if not valid:
        # Never include the connection string: it contains a password.
        raise RuntimeError("Development worker requires its isolated database and worker role")

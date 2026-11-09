"""Wait until the database host resolves and accepts TCP connections, then exit 0.

Runs before `alembic upgrade head` so a slow start of Railway's private network (or of the
database itself) does not crash the container. Prints a clear hint if it never works."""
import os
import socket
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings  # noqa: E402


def main() -> int:
    url = settings.database_url
    if url.startswith("sqlite"):
        return 0
    u = urlparse(url)
    host, port = u.hostname, u.port or 5432
    limit = float(os.getenv("DB_WAIT_SECONDS", "60"))
    start, attempt, last = time.time(), 0, ""
    print(f"[wait_for_db] waiting for {host}:{port} (up to {limit:.0f}s)", flush=True)
    while time.time() - start < limit:
        attempt += 1
        try:
            with socket.create_connection((host, port), timeout=5):
                print(f"[wait_for_db] database reachable after {attempt} attempt(s)", flush=True)
                return 0
        except socket.gaierror as e:
            last = f"DNS: cannot resolve '{host}' ({e})"
        except OSError as e:
            last = f"TCP: {e}"
        if attempt in (1, 5) or attempt % 10 == 0:
            print(f"[wait_for_db] not ready yet - {last}", flush=True)
        time.sleep(2)
    print(f"[wait_for_db] GAVE UP: {last}", flush=True)
    if host and host.endswith(".railway.internal"):
        print("[wait_for_db] HINT: *.railway.internal only works when the bot service and the Postgres service are in the "
              "SAME Railway project AND environment, and Postgres is running. Check the hostname in Postgres -> Settings -> "
              "Networking, or temporarily use ${{Postgres.DATABASE_PUBLIC_URL}} as DATABASE_URL.", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())

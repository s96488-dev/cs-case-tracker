import os
import tempfile

# Config modules read the environment on import, so set it before any test imports them.
os.environ.setdefault("BUFFER_PATH", os.path.join(tempfile.mkdtemp(), "buffer.db"))
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

"""
Shared test setup.

Settings are instantiated at import time and jwt_secret has no default, so a
value has to exist before any test module imports config.settings. setdefault,
not assignment: a real .env keeps precedence, and this only fills the gap so the
suite runs without one.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-not-used-anywhere-real")

"""The package's exception root.

Pattern from the `python-patterns` skill (ECC): one base class per package, so a caller can catch
everything this codebase raises deliberately without catching everything Python raises. Category
classes sit between the root and the specific errors to keep the hierarchy three levels deep rather
than one flat list.

The stdlib bases are kept as secondary parents on purpose: a malformed document was a ValueError
before this hierarchy existed, and callers (and the test suites) should not have to be rewritten to
keep catching it.

Layer 0: this module imports nothing.

    .venv/bin/python -c "from pinkmohawk import errors; print(errors.PinkMohawkError.__mro__)"
"""

from __future__ import annotations


class PinkMohawkError(Exception):
    """Base class for every error this package raises on purpose."""


class ValidationError(PinkMohawkError, ValueError):
    """Input, document or graph structure is malformed. Raised before any work is done."""


class RuntimeFailure(PinkMohawkError, RuntimeError):
    """A generation or ticking attempt failed at runtime."""

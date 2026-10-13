"""
ARIA API — Standard error schema.

Every router uses this model so the frontend has one error handler.

Usage in a router:

    from core.api.errors import api_error

    @router.post("/something")
    def do_something():
        if bad:
            raise api_error("validation_failed", "The input was invalid", 400)
"""

from fastapi import HTTPException
from pydantic import BaseModel


class APIErrorBody(BaseModel):
    error: str          # machine-readable code (e.g. "not_found")
    detail: str | None  # human-readable message
    status_code: int    # HTTP status


def api_error(error: str, detail: str | None = None, status_code: int = 400) -> HTTPException:
    """Create an HTTPException with the standard ARIA error body."""
    return HTTPException(
        status_code=status_code,
        detail=APIErrorBody(
            error=error,
            detail=detail,
            status_code=status_code,
        ).model_dump(),
    )

from fastapi import HTTPException

from app.services.errors import ValidationFailed

HTTP_422 = 422


def to_http(error: ValidationFailed) -> HTTPException:
    """422 с понятной картой ошибок: {"name": "...", "custom.vin": "..."}."""
    detail = {
        (f"custom.{key[3:]}" if key.startswith("cf_") else key): message
        for key, message in error.errors.items()
    }
    return HTTPException(HTTP_422, detail)

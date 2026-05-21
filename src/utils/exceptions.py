"""Enhanced error handling and custom exceptions"""

import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class APIError(BaseModel):
    """Standard API error response"""

    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None


class ZAPIException(Exception):
    """Base exception for ZAPI"""

    def __init__(
        self,
        error_code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 500,
        log_level: str = "error",
    ):
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        self.status_code = status_code

        # Log the error
        log_func = getattr(logger, log_level, logger.error)
        log_func(f"{error_code}: {message}", extra={"details": self.details})

        super().__init__(self.message)


class ValidationError(ZAPIException):
    """Validation error"""

    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            error_code="VALIDATION_ERROR",
            message=message,
            details=details,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            log_level="warning",
        )


class YouTubeError(ZAPIException):
    """YouTube API error"""

    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            error_code="YOUTUBE_ERROR",
            message=message,
            details=details,
            status_code=status.HTTP_400_BAD_REQUEST,
            log_level="error",
        )


class FacebookError(ZAPIException):
    """Facebook API error"""

    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            error_code="FACEBOOK_ERROR",
            message=message,
            details=details,
            status_code=status.HTTP_400_BAD_REQUEST,
            log_level="error",
        )


class VideoProcessingError(ZAPIException):
    """Video processing error"""

    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            error_code="VIDEO_PROCESSING_ERROR",
            message=message,
            details=details,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            log_level="error",
        )


class DatabaseError(ZAPIException):
    """Database operation error"""

    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            error_code="DATABASE_ERROR",
            message=message,
            details=details,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            log_level="error",
        )


class NotFoundError(ZAPIException):
    """Resource not found error"""

    def __init__(self, resource: str, identifier: str):
        super().__init__(
            error_code="NOT_FOUND",
            message=f"{resource} not found: {identifier}",
            details={"resource": resource, "identifier": identifier},
            status_code=status.HTTP_404_NOT_FOUND,
            log_level="warning",
        )


class DuplicateError(ZAPIException):
    """Duplicate resource error"""

    def __init__(self, resource: str, identifier: str):
        super().__init__(
            error_code="DUPLICATE_RESOURCE",
            message=f"{resource} already exists: {identifier}",
            details={"resource": resource, "identifier": identifier},
            status_code=status.HTTP_409_CONFLICT,
            log_level="warning",
        )


class RateLimitError(ZAPIException):
    """Rate limit exceeded"""

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(
            error_code="RATE_LIMIT_EXCEEDED",
            message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            log_level="warning",
        )


class ConfigurationError(ZAPIException):
    """Configuration error"""

    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            error_code="CONFIGURATION_ERROR",
            message=message,
            details=details,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            log_level="critical",
        )


def to_http_exception(exc: ZAPIException) -> HTTPException:
    """Convert ZAPIException to HTTPException"""
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
    )

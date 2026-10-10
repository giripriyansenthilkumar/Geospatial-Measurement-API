"""Custom domain exceptions and error definitions."""

from typing import Any, Optional


class GeoMeasureException(Exception):
    """Base exception for all application errors."""

    status_code: int = 400
    code: str = "INVALID_REQUEST"

    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class InvalidFileError(GeoMeasureException):
    """Raised when file content is corrupt, unreadable, or invalid."""

    status_code = 400
    code = "INVALID_FILE"


class FileNotFoundError(GeoMeasureException):
    """Raised when the requested file resource is not found."""

    status_code = 404
    code = "FILE_NOT_FOUND"


class FileNotReadyError(GeoMeasureException):
    """Raised when measurements are requested while processing."""

    status_code = 409
    code = "NOT_READY"


class FileTooLargeError(GeoMeasureException):
    """Raised when uploaded file exceeds the configured size limit."""

    status_code = 413
    code = "FILE_TOO_LARGE"


class UnsupportedTypeError(GeoMeasureException):
    """Raised when file format is not .zip (Shapefile) or .kml."""

    status_code = 415
    code = "UNSUPPORTED_TYPE"


class IncompleteShapefileError(GeoMeasureException):
    """Raised when Shapefile is missing required components (.shp, .shx, .dbf) or dataset is empty."""

    status_code = 422
    code = "INCOMPLETE_SHAPEFILE"


class InternalError(GeoMeasureException):
    """Raised for unexpected internal server errors."""

    status_code = 500
    code = "INTERNAL_ERROR"

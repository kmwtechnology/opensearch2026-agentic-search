"""
Authentication error types shared across middleware modules.
"""


class AuthConfigurationError(Exception):
    """Raised when a required auth env var (LOGIN_PASSWORD, SESSION_SECRET) is not configured."""

    pass

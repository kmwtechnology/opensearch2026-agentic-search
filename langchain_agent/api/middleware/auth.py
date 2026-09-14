"""
Authentication error types shared across middleware modules.
"""

from core.exceptions import ConfigurationError


class AuthConfigurationError(ConfigurationError):
    """Raised when a required auth env var (LOGIN_PASSWORD, SESSION_SECRET) is not configured."""

    pass

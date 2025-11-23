"""OASist Client Generator package.

A comprehensive OpenAPI client generator with support for:
- Custom headers for authenticated endpoints
- Environment variable substitution
- Auto-detection of base URLs
- Rich CLI interface with progress tracking
- Multiple schema format support (JSON/YAML)
- Automatic code formatting with Black
"""

__all__ = [
    "ClientGenerator",
    "ServiceConfig",
    "CodeFormatter",
]

from .oasist import ClientGenerator, ServiceConfig, CodeFormatter  # re-export for convenience

__version__ = "1.1.1"

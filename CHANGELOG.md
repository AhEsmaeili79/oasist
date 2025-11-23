# Changelog

All notable changes to OASist will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.1] - 2024-10-16

### Added
- **Custom headers support** - `request_headers` field for authenticated schema endpoints
- **Original base URL tracking** - Track user-provided base URL before auto-detection
- CLI flags for custom config file (`--config`, `-c`)
- CLI flags for verbose/debug logging (`--verbose`, `-v`)
- Comprehensive test suite with 30+ tests covering all major functionality
- Constants for command names and exit codes for better maintainability
- Validation for empty schemas and missing OpenAPI fields
- Warning when no services are configured in generate_all()
- Detailed error messages with specific exception types
- Documentation for environment variable substitution feature
- Documentation for custom headers usage with authentication examples

### Changed
- **ServiceConfig now tracks original_base_url** - Preserves user-specified base URL before auto-detection
- **Custom headers merge with defaults** - User headers override Accept headers if needed
- **Enhanced info display** - Shows both current and original base URL when different
- Moved all imports to top of file (including urllib.parse)
- Improved temp_file() context manager with better exception handling and cleanup
- Enhanced type hints in _load_projects() and _load_services() with proper generic types
- Better error handling with specific exception types (FileNotFoundError, PermissionError, etc.)
- Consistent return values in main() function with proper exit codes
- ConfigLoader now catches and handles invalid services gracefully with warnings
- Updated README with new CLI options, custom headers, and environment variable documentation
- Improved docstrings for all public methods

### Fixed
- Resource cleanup issue in temp_file() context manager
- Inconsistent return values from main() function
- Type hints missing List and Dict generic parameters
- Logger.debug() calls now functional with verbose mode
- Path validation now provides specific error messages
- JSON decode errors now show line and column numbers
- Import organization and removed inline import

## [1.0.0] - 2024-10-16

### Added
- Complete production-ready release
- Comprehensive input validation for ServiceConfig
- Path traversal protection in file operations
- Improved error handling with specific exception types
- Better logging with separate stdout/stderr capture
- Configuration constants for timeouts and retries
- Complete docstrings for all public methods
- .gitignore file for proper repository hygiene
- MIT LICENSE file
- CHANGELOG.md for version tracking
- Support for Python 3.8 and 3.9 in classifiers

### Changed
- Enhanced base URL auto-detection with fallback to origin
- Improved schema parsing with detailed error messages
- Better subprocess error capture (both stdout and stderr)
- Updated README with accurate feature descriptions
- Aligned dependency versions across requirements.txt and pyproject.toml
- Standardized line-length configuration to 120 characters
- Changed development status to "Production/Stable"

### Fixed
- Version inconsistency between pyproject.toml and __init__.py
- Line-length configuration conflict between pyproject.toml and ruff.toml
- python-dotenv version mismatch
- Security issues with path traversal
- Missing Python version classifiers
- Fragile base URL auto-detection logic
- Missing error details when schema parsing fails

### Removed
- Unused root __init__.py file

### Security
- Added path traversal validation in ClientGenerator.generate()
- Added output directory validation in ServiceConfig.__post_init__()
- Added URL format validation for schema_url

## [0.1.6] - 2024-XX-XX
- Bug fixes and improvements

## [0.1.5] - 2024-XX-XX
- Bug fixes and improvements

## [0.1.4] - 2024-XX-XX
- Bug fixes and improvements

## [0.1.3] - 2024-XX-XX
- Bug fixes and improvements

## [0.1.2] - 2024-XX-XX
- Bug fixes and improvements

## [0.1.1] - 2024-XX-XX
- Initial public release
- Basic client generation functionality
- Orval-inspired configuration format
- Rich CLI interface

[1.1.0]: https://github.com/AhEsmaeili79/oasist/releases/tag/v1.1.0
[1.0.0]: https://github.com/AhEsmaeili79/oasist/releases/tag/v1.0.0
[0.1.6]: https://github.com/AhEsmaeili79/oasist/releases/tag/v0.1.6
[0.1.5]: https://github.com/AhEsmaeili79/oasist/releases/tag/v0.1.5
[0.1.4]: https://github.com/AhEsmaeili79/oasist/releases/tag/v0.1.4
[0.1.3]: https://github.com/AhEsmaeili79/oasist/releases/tag/v0.1.3
[0.1.2]: https://github.com/AhEsmaeili79/oasist/releases/tag/v0.1.2
[0.1.1]: https://github.com/AhEsmaeili79/oasist/releases/tag/v0.1.1


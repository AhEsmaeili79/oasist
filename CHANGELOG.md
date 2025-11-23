# Changelog

All notable changes to OASist will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.1] - 2025-11-24

### Added
- **API Versioning Support** - Generate and manage multiple API versions simultaneously
  - Support for versioned projects with multiple API versions
  - Each version stored in its own directory (e.g., `1.0.0/`, `1.1.0/`)
  - Version detection from OpenAPI `info.version` field
  - Preserves exact version strings (no normalization for directory names)
- **Incremental Generation** - Generate only changed endpoints/models for new versions
  - `generation_mode` option: `"full"` (complete client) or `"changed"` (incremental)
  - Automatic change detection between API versions
  - Only generates new/modified endpoints and models
  - Unchanged code imported from base version (cleaner structure)
  - Base version always uses full generation automatically
- **Schema Comparison** - Automatic change detection
  - `SchemaComparator` class for comparing OpenAPI schemas
  - Endpoint comparison (new, modified, unchanged, removed)
  - Model comparison (new, modified, unchanged)
  - Deep schema normalization for accurate comparison
- **Version Registry** - Track version metadata and changes
  - `version_registry.json` file per project
  - Tracks generated versions, timestamps, endpoints, models
  - Stores change detection results for incremental versions
  - Schema caching for efficient comparison
- **Version Selector** - Easy client version selection
  - `get_client()` function for versioned projects
  - Automatic version selection with fallback to latest
  - Dynamic imports using `importlib` for directory names starting with numbers
- **CLI Enhancements** - New commands and options
  - `oasist versions <service>` - List all versions for a service
  - `oasist generate <service> --version <version>` - Generate specific version
  - Enhanced `oasist list` - Shows version information for versioned projects
- **Schema Caching** - Efficient base version schema storage
  - Base version schemas cached in `.schema_cache/` directory
  - Enables fast comparison for incremental generation
  - Automatic cache management
- **Local File Support** - Support for local schema files
  - Can use local file paths in `target` field (e.g., `"./schemas/v1.0.0.json"`)
  - Automatic path resolution (relative to project root)
  - Works with both JSON and YAML files
- **Clean Directory Structure** - No empty directories for unchanged code
  - Only creates directories for modules with actual changes
  - Unchanged endpoints/models accessible via imports from base version
  - Significantly cleaner output structure

### Changed
- **Configuration Format** - Extended for versioning support
  - Added `versioning` section with `enabled`, `auto_detect`, `base_version`, `generation_mode`
  - Added `versions` object for version-specific configurations
  - Backward compatible with existing non-versioned configurations
- **Client Generation** - Enhanced for versioned projects
  - `ClientGenerator.generate()` now supports `version` parameter
  - Automatic version detection when `auto_detect` is enabled
  - Base version schema caching for incremental generation
- **Entry Point Generation** - Dynamic imports for versioned clients
  - Uses `importlib` for importing from directories starting with numbers
  - Version selector with automatic latest version detection
  - Improved error messages for missing versions
- **Schema Fetching** - Enhanced for better compatibility
  - Support for local file paths in addition to URLs
  - Improved error handling for network issues
  - Browser-like headers to bypass bot protection
  - IPv4 forcing for problematic hosts
  - Text cleaning to remove control characters that cause parsing errors
- **Test Suite** - Comprehensive versioning tests
  - 55+ versioning-specific tests
  - Unit tests for all versioning components
  - Integration tests for end-to-end workflows
  - All tests passing (193 passed, 9 skipped)

### Fixed
- **Import Path Issues** - Fixed imports for directories starting with numbers
  - Uses `importlib.util` for dynamic module loading
  - Proper handling of version directory names
- **Test Mocking** - Fixed network-related test failures
  - Updated tests to mock `requests.Session` instead of `requests.get`
  - All network tests now properly mocked
- **URL Validation** - More flexible validation
  - Allows any URL format, validates during fetch with better error messages
- **Timeout Handling** - Improved timeout test coverage
  - Proper mocking of `subprocess.Popen` for timeout scenarios

### Technical Details
- **Version Normalization**
  - Directory names: Preserves exact version string (e.g., `1.0.0`)
  - Import names: Normalized for Python (e.g., `v1_0_0`)
- **Change Detection Algorithm**
  - Compares endpoint signatures (method + path)
  - Compares model schemas with deep normalization
  - Tracks dependencies for incremental generation
- **Incremental Generation Flow**
  1. Load base version schema from cache
  2. Compare with new version schema
  3. Filter schema to include only changes + dependencies
  4. Generate client with filtered schema
  5. Create import stubs for unchanged code
  6. Update version registry with change information

## [1.1.1] - 2025-10-16

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

## [1.0.0] - 2025-10-16

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

[1.2.1]: https://github.com/AhEsmaeili79/oasist/releases/tag/v1.2.1
[1.1.1]: https://github.com/AhEsmaeili79/oasist/releases/tag/v1.1.1
[1.1.0]: https://github.com/AhEsmaeili79/oasist/releases/tag/v1.1.0
[1.0.0]: https://github.com/AhEsmaeili79/oasist/releases/tag/v1.0.0
[0.1.6]: https://github.com/AhEsmaeili79/oasist/releases/tag/v0.1.6
[0.1.5]: https://github.com/AhEsmaeili79/oasist/releases/tag/v0.1.5
[0.1.4]: https://github.com/AhEsmaeili79/oasist/releases/tag/v0.1.4
[0.1.3]: https://github.com/AhEsmaeili79/oasist/releases/tag/v0.1.3
[0.1.2]: https://github.com/AhEsmaeili79/oasist/releases/tag/v0.1.2
[0.1.1]: https://github.com/AhEsmaeili79/oasist/releases/tag/v0.1.1


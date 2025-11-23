#!/usr/bin/env python
"""OASist - OpenAPI Client Generator

Generates Python API clients from OpenAPI/Swagger specifications.

Architecture Notes:
- Uses design patterns (Strategy, Command, Dataclass) for maintainability
- While this adds some complexity, it provides:
  * Better testability and extensibility
  * Clear separation of concerns
  * Type safety with dataclasses
  * Easy addition of new commands and parsers
- For simple use cases, the CLI provides a straightforward interface
- For advanced use cases, the modular design allows programmatic usage
"""
import subprocess
import requests
import yaml
import json
import logging
import os
import re
import shutil
import tempfile
import sys
import importlib.util
from pathlib import Path
from typing import Optional, Dict, Any, Protocol, Generator, List
from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import datetime
from abc import ABC, abstractmethod
from urllib.parse import urlparse
from dotenv import load_dotenv

from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.logging import RichHandler
from rich import box
from rich.text import Text
from rich.rule import Rule
from rich.align import Align

# ============================================================================
# CONFIGURATION
# ============================================================================
OUTPUT_DIR = "./clients"
CONFIG_FILE = "oasist_config.json"
HTTP_TIMEOUT = 30  # seconds
RICH_THEME = Theme({
    "info": "bold cyan", "warning": "bold yellow", "error": "bold red",
    "success": "bold green", "accent": "bold magenta", "dim": "dim"
})

# Command names
CMD_LIST = "list"
CMD_GENERATE = "generate"
CMD_GENERATE_ALL = "generate-all"
CMD_INFO = "info"
CMD_VERSIONS = "versions"
CMD_HELP = "help"

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1

console = Console(theme=RICH_THEME)
logging.basicConfig(level=logging.INFO, format='%(message)s',
    handlers=[RichHandler(console=console, rich_tracebacks=True, show_time=False, show_path=False)])
logger = logging.getLogger("oasist")
load_dotenv()

# ============================================================================
# UTILITIES
# ============================================================================
def substitute_env_vars(text: str) -> str:
    """Replace ${VAR} or ${VAR:default} with env values.
    
    Warns if environment variable is not found and no default is provided.
    """
    if not isinstance(text, str):
        return text
    
    def replace_var(match):
        var_name = match.group(1)
        default_value = match.group(2)
        env_value = os.getenv(var_name)
        
        if env_value is not None:
            return env_value
        elif default_value is not None:
            return default_value
        else:
            logger.warning(f"Environment variable '{var_name}' not found and no default provided")
            return match.group(0)  # Return original placeholder
    
    return re.sub(r'\$\{([^}:]+)(?::([^}]*))?\}', replace_var, text)

def substitute_recursive(data: Any) -> Any:
    """Recursively substitute environment variables in nested data structures.
    
    Traverses dictionaries, lists, and strings to replace ${VAR} or ${VAR:default}
    patterns with environment variable values.
    
    Args:
        data: Data structure (str, dict, list, or primitive) to process
        
    Returns:
        Processed data with environment variables substituted
    """
    if isinstance(data, str):
        return substitute_env_vars(data)
    if isinstance(data, dict):
        return {k: substitute_recursive(v) for k, v in data.items()}
    if isinstance(data, list):
        return [substitute_recursive(item) for item in data]
    return data

@contextmanager
def temp_file(content: Dict[str, Any], as_json: bool = True) -> Generator[Path, None, None]:
    """Context manager for temp files with auto cleanup.
    
    Args:
        content: Dictionary content to write to file
        as_json: If True, write as JSON; otherwise write as YAML
        
    Yields:
        Path to the temporary file
        
    Raises:
        IOError: If file creation/write operations fail
    """
    suffix = '.json' if as_json else '.yaml'
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='w', encoding='utf-8')
    tmp_path = Path(tmp.name)
    
    try:
        # Write content to file
        if as_json:
            json.dump(content, tmp, ensure_ascii=False, indent=2)
        else:
            yaml.safe_dump(content, tmp, sort_keys=False, allow_unicode=True)
        tmp.flush()  # Ensure data is written
        tmp.close()  # Close file handle before yielding
        
        yield tmp_path
    except Exception as e:
        # Close file if still open (during file creation)
        try:
            tmp.close()
        except:
            pass
        # Only wrap IOError for file operations, not user code exceptions
        if tmp_path.exists():
            # File was created successfully, user code raised exception
            raise
        else:
            # File creation failed
            raise IOError(f"Failed to create temporary file: {e}") from e
    finally:
        # Always cleanup temp file
        tmp_path.unlink(missing_ok=True)

# ============================================================================
# STRATEGY PATTERN - Schema Parsing
# ============================================================================
class SchemaParser(Protocol):
    """Protocol for schema parsing strategies."""
    def parse(self, text: str) -> Dict[str, Any]: ...

class JSONParser:
    """JSON schema parser."""
    def parse(self, text: str) -> Dict[str, Any]:
        return json.loads(text)

class YAMLParser:
    """YAML schema parser."""
    def parse(self, text: str) -> Dict[str, Any]:
        return yaml.safe_load(text)

# ============================================================================
# DATA CLASSES
# ============================================================================
@dataclass
class VersioningConfig:
    """Versioning configuration for a project."""
    enabled: bool = False
    auto_detect: bool = False
    base_version: Optional[str] = None
    generation_mode: Optional[str] = "full"  # "full" or "changed"
    
    def __post_init__(self):
        """Validate generation_mode."""
        if self.generation_mode and self.generation_mode.lower() not in ("full", "changed"):
            raise ValueError(f"generation_mode must be 'full' or 'changed', got '{self.generation_mode}'")
        if self.generation_mode:
            self.generation_mode = self.generation_mode.lower()

@dataclass
class VersionConfig:
    """Configuration for a specific API version."""
    version: str
    input: Dict[str, Any] = field(default_factory=dict)
    output: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Substitute environment variables in configuration."""
        self.input = substitute_recursive(self.input)
        self.output = substitute_recursive(self.output)

@dataclass
class ServiceConfig:
    """Service configuration with auto env var substitution and validation."""
    name: str
    schema_url: str
    output_dir: str
    base_url: str = ""
    package_name: str = ""
    request_params: Dict[str, str] = field(default_factory=dict)
    request_headers: Dict[str, str] = field(default_factory=dict)
    prefer_json: bool = False
    disable_post_hooks: bool = True
    format_with_black: bool = True  # Auto-format generated code with Black
    original_base_url: str = field(default="", init=False)  # Track original before auto-detection
    versioning: Optional[VersioningConfig] = None  # Versioning configuration
    versions: Dict[str, VersionConfig] = field(default_factory=dict)  # Version-specific configs
    
    def __post_init__(self):
        """Auto-substitute env vars, validate, and generate defaults."""
        # Substitute environment variables in strings
        for attr in ('name', 'schema_url', 'output_dir', 'package_name', 'base_url'):
            setattr(self, attr, substitute_env_vars(getattr(self, attr)))
        
        # Substitute environment variables in dictionaries
        self.request_params = substitute_recursive(self.request_params)
        self.request_headers = substitute_recursive(self.request_headers)
        
        # Validate required fields
        if not self.name or not self.name.strip():
            raise ValueError("Service name cannot be empty")
        if not self.schema_url or not self.schema_url.strip():
            raise ValueError(f"Schema URL cannot be empty for service '{self.name}'")
        if not self.output_dir or not self.output_dir.strip():
            raise ValueError(f"Output directory cannot be empty for service '{self.name}'")
        
        # Validate URL or file path format
        if not (self.schema_url.startswith(('http://', 'https://')) or 
                Path(self.schema_url).exists() or 
                Path(Path.cwd() / self.schema_url).exists()):
            # Don't raise error here - let it fail during fetch with a better error message
            pass
        
        # Track original base_url before auto-detection
        self.original_base_url = self.base_url
        
        # Auto-detect base URL with fallback logic if not provided
        if not self.base_url:
            # Try common patterns: /api/, /openapi, /swagger
            for pattern in ['/api/', '/openapi', '/swagger']:
                if pattern in self.schema_url:
                    self.base_url = self.schema_url.rsplit(pattern, 1)[0]
                    break
            # Fallback to origin (protocol + domain)
            if not self.base_url:
                parsed = urlparse(self.schema_url)
                self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # Generate package name from service name if not provided
        self.package_name = (self.package_name or 
                           self.name.lower().replace('-', '_').replace(' ', '_'))
        
        # Validate output_dir for path traversal and absolute paths
        output_path = Path(self.output_dir)
        # Check for path traversal, absolute paths, and Unix-style absolute paths
        is_unix_absolute = self.output_dir.startswith('/')
        if '..' in self.output_dir or output_path.is_absolute() or is_unix_absolute:
            raise ValueError(f"Output directory must be relative and cannot contain '..': '{self.output_dir}'")

# ============================================================================
# SCHEMA PROCESSOR
# ============================================================================
class SchemaProcessor:
    """Processes and sanitizes OpenAPI schemas."""
    
    HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    
    @staticmethod
    def fetch(url: str, params: Dict[str, str], prefer_json: bool, custom_headers: Dict[str, str] = None) -> Optional[Dict[str, Any]]:
        """Fetch schema with format preference and retry logic.
        
        Args:
            url: URL or file path to fetch schema from
            params: Query parameters for the request (ignored for file paths)
            prefer_json: If True, prefer JSON format over YAML
            custom_headers: Optional custom headers to include in request (ignored for file paths)
            
        Returns:
            Parsed schema dictionary or None on failure
        """
        # Check if it's a local file path
        if not url.startswith(('http://', 'https://')):
            # It's a file path
            file_path = Path(url)
            if not file_path.is_absolute():
                # Make it relative to current working directory
                file_path = Path.cwd() / file_path
            
            with console.status("[accent]Loading schema from file...", spinner="dots"):
                try:
                    if not file_path.exists():
                        logger.error(f"Schema file not found: {file_path}")
                        return None
                    
                    with open(file_path, 'r', encoding='utf-8') as f:
                        response_text = f.read()
                    
                    # Clean response text - remove BOM and control characters
                    if response_text.startswith('\ufeff'):
                        response_text = response_text[1:]
                    import re
                    response_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', response_text)
                    
                    # Try preferred format first, then fallback
                    parsers = ([JSONParser(), YAMLParser()] if prefer_json or str(file_path).lower().endswith('.json')
                              else [YAMLParser(), JSONParser()])
                    
                    last_error = None
                    for i, parser in enumerate(parsers):
                        try:
                            schema = parser.parse(response_text)
                            if schema and isinstance(schema, dict):
                                if not schema.get('openapi') and not schema.get('swagger'):
                                    logger.warning("Schema missing 'openapi' or 'swagger' version field")
                                if not schema.get('paths') and not schema.get('webhooks'):
                                    logger.warning("Schema has no 'paths' or 'webhooks' defined")
                                return schema
                            elif schema is not None:
                                logger.error(f"Schema is not a dictionary: {type(schema)}")
                        except json.JSONDecodeError as e:
                            last_error = f"JSON parsing failed: {e}"
                            logger.debug(f"Parser {i+1} (JSON) failed: {e}")
                        except yaml.YAMLError as e:
                            last_error = f"YAML parsing failed: {e}"
                            logger.debug(f"Parser {i+1} (YAML) failed: {e}")
                        except Exception as e:
                            last_error = f"Parsing failed: {e}"
                            logger.debug(f"Parser {i+1} failed: {e}")
                    
                    if last_error:
                        logger.error(f"All parsers failed. Last error: {last_error}")
                    return None
                    
                except IOError as e:
                    logger.error(f"Failed to read schema file: {e}")
                    return None
                except Exception as e:
                    logger.error(f"Error loading schema from file: {e}")
                    return None
        
        # It's a URL - proceed with HTTP request
        headers = {
            'Accept': 'application/vnd.oai.openapi+json, application/json' if prefer_json 
                      else 'application/yaml, text/yaml, application/x-yaml, text/plain',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',  # Removed 'br' (Brotli) to avoid decompression issues
            'Connection': 'keep-alive'
        }
        
        # Merge custom headers (they override defaults)
        if custom_headers:
            headers.update(custom_headers)
        
        with console.status("[accent]Fetching schema...", spinner="dots"):
            try:
                # Force IPv4 to avoid IPv6 connection issues
                # Create a custom adapter that prefers IPv4
                from requests.adapters import HTTPAdapter
                from urllib3.util.connection import create_connection
                import socket
                
                class IPv4HTTPAdapter(HTTPAdapter):
                    def init_poolmanager(self, *args, **kwargs):
                        # Force IPv4
                        import urllib3.util.connection as urllib3_conn
                        orig_create_connection = urllib3_conn.create_connection
                        def patched_create_connection(address, *args, **kwargs):
                            host, port = address
                            # Force IPv4
                            return orig_create_connection((socket.gethostbyname(host), port), *args, **kwargs)
                        urllib3_conn.create_connection = patched_create_connection
                        return super().init_poolmanager(*args, **kwargs)
                
                # Use session with IPv4 adapter for problematic hosts
                session = requests.Session()
                if 'sub.giggo.site' in url or 'giggo.site' in url:
                    session.mount('https://', IPv4HTTPAdapter())
                
                response = session.get(url, headers=headers, params=params, timeout=HTTP_TIMEOUT)
                response.raise_for_status()
                
                # Check if response is empty
                if not response.text or not response.text.strip():
                    logger.error("Received empty response from schema URL")
                    return None
                
                # Clean response text - remove BOM and control characters that might cause parsing issues
                response_text = response.text
                # Remove BOM if present
                if response_text.startswith('\ufeff'):
                    response_text = response_text[1:]
                # Remove problematic control characters (but keep newlines \n, tabs \t, carriage return \r)
                import re
                # Remove ASCII control characters except newline (0x0a), tab (0x09), and carriage return (0x0d)
                # Also remove Unicode control characters (C1 control codes 0x80-0x9f and other control chars)
                # This removes: null, vertical tab, form feed, DEL, and Unicode control characters
                # Keep printable ASCII (0x20-0x7e) and valid whitespace (0x09, 0x0a, 0x0d)
                response_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', response_text)
                
                # Try preferred format first, then fallback
                parsers = ([JSONParser(), YAMLParser()] if prefer_json or url.lower().endswith('.json')
                          else [YAMLParser(), JSONParser()])
                
                last_error = None
                for i, parser in enumerate(parsers):
                    try:
                        schema = parser.parse(response_text)
                        if schema and isinstance(schema, dict):
                            # Validate schema has required OpenAPI fields
                            if not schema.get('openapi') and not schema.get('swagger'):
                                logger.warning("Schema missing 'openapi' or 'swagger' version field")
                            if not schema.get('paths') and not schema.get('webhooks'):
                                logger.warning("Schema has no 'paths' or 'webhooks' defined")
                            return schema
                        elif schema is not None:
                            logger.error(f"Schema is not a dictionary: {type(schema)}")
                    except json.JSONDecodeError as e:
                        last_error = f"JSON parsing failed: {e}"
                        logger.debug(f"Parser {i+1} (JSON) failed: {e}")
                    except yaml.YAMLError as e:
                        last_error = f"YAML parsing failed: {e}"
                        logger.debug(f"Parser {i+1} (YAML) failed: {e}")
                    except Exception as e:
                        last_error = f"Parsing failed: {e}"
                        logger.debug(f"Parser {i+1} failed: {e}")
                
                # If all parsers failed, log the last error
                if last_error:
                    logger.error(f"All parsers failed. Last error: {last_error}")
                return None
                
            except requests.exceptions.Timeout:
                logger.error(f"Request timeout after {HTTP_TIMEOUT}s")
                return None
            except requests.exceptions.ConnectionError as e:
                error_msg = str(e)
                # Provide helpful message for common connection issues
                if "Connection reset by peer" in error_msg or "104" in error_msg:
                    logger.error(f"Connection error: {e}")
                    logger.warning("This may be due to bot protection (e.g., Cloudflare) blocking automated requests.")
                    logger.info("Try accessing the URL in a browser first, or use a local file path instead.")
                elif "Network is unreachable" in error_msg or "101" in error_msg:
                    logger.error(f"Network error: {e}")
                    logger.warning("Cannot reach the server. Check your network connection and firewall settings.")
                    logger.info(f"Try: ping {urlparse(url).netloc} to test connectivity")
                else:
                    logger.error(f"Connection error: {e}")
                return None
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP error {e.response.status_code}: {e}")
                return None
            except Exception as e:
                logger.error(f"Schema fetch failed: {e}")
                return None
    
    @staticmethod
    def sanitize_security(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize invalid security requirement formats to OpenAPI spec."""
        paths = schema.get('paths', {})
        if not isinstance(paths, dict):
            return schema
        
        for path_item in paths.values():
            if not isinstance(path_item, dict):
                continue
            for method, op in path_item.items():
                if method not in SchemaProcessor.HTTP_METHODS or not isinstance(op, dict):
                    continue
                
                security = op.get('security')
                if isinstance(security, dict):
                    # Convert dict to list of separate requirements (OR logic)
                    op['security'] = [{k: []} for k in security.keys()]
                elif isinstance(security, list):
                    op['security'] = [{k: v if isinstance(v, list) else [] 
                                      for k, v in req.items()} 
                                     for req in security if isinstance(req, dict)]
        return schema

# ============================================================================
# SCHEMA COMPARATOR
# ============================================================================
class SchemaComparator:
    """Compares OpenAPI schemas to detect changes between versions."""
    
    @staticmethod
    def get_endpoint_signature(path: str, method: str) -> str:
        """Create consistent endpoint signature.
        
        Args:
            path: API path (e.g., "/api/user/{id}")
            method: HTTP method (e.g., "get", "post")
            
        Returns:
            Endpoint signature string (e.g., "GET /api/user/{id}")
        """
        return f"{method.upper()} {path}"
    
    @staticmethod
    def normalize_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize schema for comparison by removing metadata and sorting keys.
        
        Args:
            schema: Schema dictionary to normalize
            
        Returns:
            Normalized schema dictionary
        """
        if not isinstance(schema, dict):
            return schema
        
        # Create a copy to avoid modifying original
        normalized = {}
        
        # Sort keys for consistent comparison
        for key in sorted(schema.keys()):
            value = schema[key]
            
            # Skip metadata fields that don't affect functionality
            if key in ('description', 'summary', 'example', 'examples', 'externalDocs'):
                continue
            
            # Recursively normalize nested structures
            if isinstance(value, dict):
                normalized[key] = SchemaComparator.normalize_schema(value)
            elif isinstance(value, list):
                normalized[key] = [
                    SchemaComparator.normalize_schema(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                normalized[key] = value
        
        return normalized
    
    @staticmethod
    def compare_operation(base_op: Dict[str, Any], new_op: Dict[str, Any]) -> bool:
        """Compare two operation objects to see if they're identical.
        
        Args:
            base_op: Base operation object
            new_op: New operation object
            
        Returns:
            True if operations are identical, False otherwise
        """
        base_norm = SchemaComparator.normalize_schema(base_op)
        new_norm = SchemaComparator.normalize_schema(new_op)
        return base_norm == new_norm
    
    @staticmethod
    def compare_endpoints(base_schema: Dict[str, Any], new_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Compare endpoints between two schemas.
        
        Args:
            base_schema: Base version schema
            new_schema: New version schema
            
        Returns:
            Dictionary with keys: 'new', 'modified', 'unchanged', 'removed'
            Each contains a list of endpoint signatures
        """
        result = {
            'new': [],
            'modified': [],
            'unchanged': [],
            'removed': []
        }
        
        base_paths = base_schema.get('paths', {})
        new_paths = new_schema.get('paths', {})
        
        # Extract all endpoints from both schemas
        base_endpoints = {}
        new_endpoints = {}
        
        for path, path_item in base_paths.items():
            if isinstance(path_item, dict):
                for method in SchemaProcessor.HTTP_METHODS:
                    if method in path_item:
                        signature = SchemaComparator.get_endpoint_signature(path, method)
                        base_endpoints[signature] = path_item[method]
        
        for path, path_item in new_paths.items():
            if isinstance(path_item, dict):
                for method in SchemaProcessor.HTTP_METHODS:
                    if method in path_item:
                        signature = SchemaComparator.get_endpoint_signature(path, method)
                        new_endpoints[signature] = path_item[method]
        
        # Compare endpoints
        all_endpoints = set(base_endpoints.keys()) | set(new_endpoints.keys())
        
        for signature in all_endpoints:
            if signature in new_endpoints and signature not in base_endpoints:
                result['new'].append(signature)
            elif signature in base_endpoints and signature not in new_endpoints:
                result['removed'].append(signature)
            elif signature in base_endpoints and signature in new_endpoints:
                # Compare operations
                if SchemaComparator.compare_operation(base_endpoints[signature], new_endpoints[signature]):
                    result['unchanged'].append(signature)
                else:
                    result['modified'].append(signature)
        
        return result
    
    @staticmethod
    def compare_models(base_schema: Dict[str, Any], new_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Compare models/schemas between two schemas.
        
        Args:
            base_schema: Base version schema
            new_schema: New version schema
            
        Returns:
            Dictionary with keys: 'new', 'modified', 'unchanged'
            Each contains a list of model names
        """
        result = {
            'new': [],
            'modified': [],
            'unchanged': []
        }
        
        base_schemas = base_schema.get('components', {}).get('schemas', {})
        new_schemas = new_schema.get('components', {}).get('schemas', {})
        
        if not isinstance(base_schemas, dict):
            base_schemas = {}
        if not isinstance(new_schemas, dict):
            new_schemas = {}
        
        # Compare all models
        all_models = set(base_schemas.keys()) | set(new_schemas.keys())
        
        for model_name in all_models:
            if model_name in new_schemas and model_name not in base_schemas:
                result['new'].append(model_name)
            elif model_name in base_schemas and model_name in new_schemas:
                # Compare schema structures
                base_norm = SchemaComparator.normalize_schema(base_schemas[model_name])
                new_norm = SchemaComparator.normalize_schema(new_schemas[model_name])
                
                if base_norm == new_norm:
                    result['unchanged'].append(model_name)
                else:
                    result['modified'].append(model_name)
        
        return result

# ============================================================================
# VERSION DETECTOR
# ============================================================================
class VersionDetector:
    """Detects and normalizes API versions from OpenAPI schemas."""
    
    @staticmethod
    def detect_from_schema(schema: Dict[str, Any]) -> Optional[str]:
        """Extract version from OpenAPI schema.
        
        Args:
            schema: OpenAPI schema dictionary
            
        Returns:
            Version string from info.version, or None if not found.
            Preserves exact string (no normalization).
        """
        info = schema.get('info', {})
        if not isinstance(info, dict):
            return None
        
        version = info.get('version')
        if version is None:
            return None
        
        # Preserve exact version string (no normalization)
        return str(version) if version else None
    
    @staticmethod
    def normalize_for_directory(version: str) -> str:
        """Convert version string to valid directory name.
        
        Args:
            version: Version string (e.g., "v1.0.0", "1.0.0")
            
        Returns:
            Directory-safe version string. Preserves structure but replaces
            invalid filesystem characters.
        """
        # Replace invalid filesystem characters but preserve structure
        # Keep dots, dashes, underscores, alphanumeric
        import re
        # Replace any characters that aren't alphanumeric, dots, dashes, or underscores
        normalized = re.sub(r'[^a-zA-Z0-9._-]', '_', version)
        return normalized
    
    @staticmethod
    def normalize_for_import(version: str) -> str:
        """Convert version string to valid Python module name.
        
        Args:
            version: Version string (e.g., "v1.0.0", "1.0.0")
            
        Returns:
            Python-importable module name (e.g., "v1_0_0", "v1_0_0")
        """
        # Replace dots and other invalid Python identifier chars with underscores
        import re
        # Replace dots and other non-alphanumeric (except underscore) with underscore
        normalized = re.sub(r'[^a-zA-Z0-9_]', '_', version)
        # Ensure it doesn't start with a number (Python requirement)
        if normalized and normalized[0].isdigit():
            normalized = 'v' + normalized
        return normalized

# ============================================================================
# CODE FORMATTER
# ============================================================================
class CodeFormatter:
    """Formats generated Python code using Black."""
    
    @staticmethod
    def is_black_available() -> bool:
        """Check if Black is installed and available.
        
        Returns:
            True if Black is available, False otherwise
        """
        try:
            result = subprocess.run(
                ['black', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return False
    
    @staticmethod
    def format_directory(directory: Path) -> bool:
        """Format all Python files in directory using Black.
        
        Args:
            directory: Directory containing Python files to format
            
        Returns:
            True if formatting succeeded or was skipped, False on error
        """
        if not directory.exists() or not directory.is_dir():
            logger.warning(f"Directory {directory} does not exist or is not a directory")
            return False
        
        # Check if Black is available
        if not CodeFormatter.is_black_available():
            logger.warning("Black is not installed. Skipping code formatting.")
            logger.info("To enable formatting, install Black: pip install black")
            return True  # Not an error, just skip formatting
        
        # Count Python files first
        python_files = list(directory.rglob("*.py"))
        total_files = len(python_files)
        
        if total_files == 0:
            logger.info("No Python files found to format")
            return True
        
        logger.info(f"Formatting {total_files} Python file(s) with Black...")
        
        try:
            # Use Progress bar to show formatting progress
            # Helper function to truncate and format file names with fixed width
            def format_file_name(file_path: str, prefix: str = "Reformatting") -> str:
                """Format file name with fixed width for stable progress bar."""
                file_name = Path(file_path).name if file_path else "Starting..."
                # Fixed display width for the entire description to keep bar stable
                # This is the actual visible width (markup codes don't count)
                display_width = 50
                prefix_text = f"{prefix}: "
                prefix_display_len = len(prefix_text)  # Actual display length
                available_width = display_width - prefix_display_len
                
                # Truncate filename if needed
                if len(file_name) > available_width:
                    file_name = file_name[:available_width-3] + "..."
                
                # Pad filename to ensure consistent total display width
                # The padding is in the actual displayed text, not including markup
                padded_name = file_name.ljust(available_width)
                return f"[accent]{prefix_text}[/accent]{padded_name}"
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}", style="dim"),
                BarColumn(bar_width=None),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("({task.completed}/{task.total} files)"),
                TimeElapsedColumn(),
                console=console,
                transient=False
            ) as progress:
                task = progress.add_task(
                    format_file_name("", "Formatting"),
                    total=total_files
                )
                
                # Run Black without --quiet to capture output
                process = subprocess.Popen(
                    ['black', str(directory)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                processed_files = 0
                reformatted_files = []
                
                # Parse output line by line
                for line in process.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Black outputs lines like:
                    # - "reformatted /path/to/file.py"
                    # - "would reformat /path/to/file.py" (in check mode)
                    # - "All done! ✨ 🍰 ✨"
                    # - "X files reformatted, Y files left unchanged."
                    if line.startswith("reformatted "):
                        file_path = line.replace("reformatted ", "").strip()
                        reformatted_files.append(file_path)
                        processed_files += 1
                        progress.update(
                            task,
                            advance=1,
                            description=format_file_name(file_path, "Reformatting")
                        )
                        logger.debug(f"Reformatted: {file_path}")
                    elif line.startswith("would reformat "):
                        file_path = line.replace("would reformat ", "").strip()
                        processed_files += 1
                        progress.update(
                            task,
                            advance=1,
                            description=format_file_name(file_path, "Would reformat")
                        )
                    elif "files reformatted" in line or "files left unchanged" in line:
                        # Summary line - extract numbers to update progress
                        logger.info(f"Black: {line}")
                        # Parse summary like "X files reformatted, Y files left unchanged."
                        reformatted_match = re.search(r'(\d+)\s+files?\s+reformatted', line)
                        unchanged_match = re.search(r'(\d+)\s+files?\s+left\s+unchanged', line)
                        
                        total_reformatted = 0
                        total_unchanged = 0
                        if reformatted_match:
                            total_reformatted = int(reformatted_match.group(1))
                        if unchanged_match:
                            total_unchanged = int(unchanged_match.group(1))
                        
                        # Update progress to reflect all processed files from summary
                        total_processed = total_reformatted + total_unchanged
                        if total_processed > 0 and total_processed <= total_files:
                            progress.update(task, completed=total_processed)
                    elif "All done!" in line:
                        # Completion message
                        logger.debug(line)
                    elif line and not line.startswith("Using configuration"):
                        # Other output (errors, warnings, etc.)
                        if "error" in line.lower() or "warning" in line.lower():
                            logger.warning(f"Black: {line}")
                        else:
                            logger.debug(f"Black: {line}")
                
                # Wait for process to complete
                returncode = process.wait(timeout=300)
                
                # Update progress to 100% if not already there
                if processed_files < total_files:
                    progress.update(task, completed=total_files)
                
                if returncode == 0:
                    if reformatted_files:
                        logger.info(f"✓ Code formatted successfully: {len(reformatted_files)} file(s) reformatted")
                    else:
                        logger.info("✓ Code formatting complete: All files already formatted")
                    return True
                else:
                    logger.warning(f"Black formatting completed with exit code {returncode}")
                    if processed_files > 0:
                        logger.info(f"Processed {processed_files} file(s)")
                    return True  # Still consider success if files were processed
                    
        except subprocess.TimeoutExpired:
            logger.error("Black formatting timeout after 300s")
            return False
        except Exception as e:
            logger.error(f"Black formatting failed: {e}")
            return False

# ============================================================================
# VERSION REGISTRY
# ============================================================================
class VersionRegistry:
    """Manages version registry files for tracking API versions."""
    
    @staticmethod
    def load(registry_path: Path) -> Dict[str, Any]:
        """Load version registry from file.
        
        Args:
            registry_path: Path to version_registry.json file
            
        Returns:
            Registry data dictionary, or default structure if file doesn't exist
        """
        if not registry_path.exists():
            return {
                "versions": {},
                "metadata": {
                    "base_version": None,
                    "latest_version": None
                }
            }
        
        try:
            with open(registry_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load version registry: {e}")
            return {
                "versions": {},
                "metadata": {
                    "base_version": None,
                    "latest_version": None
                }
            }
    
    @staticmethod
    def save(registry_path: Path, data: Dict[str, Any]) -> bool:
        """Save version registry to file.
        
        Args:
            registry_path: Path to version_registry.json file
            data: Registry data dictionary
            
        Returns:
            True if save succeeded, False otherwise
        """
        try:
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            with open(registry_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except (IOError, OSError) as e:
            logger.error(f"Failed to save version registry: {e}")
            return False
    
    @staticmethod
    def add_version(registry_path: Path, version: str, metadata: Dict[str, Any]) -> bool:
        """Add or update version entry in registry.
        
        Args:
            registry_path: Path to version_registry.json file
            version: Version string
            metadata: Version metadata (generated_at, openapi_version, schema_url, etc.)
            
        Returns:
            True if update succeeded, False otherwise
        """
        data = VersionRegistry.load(registry_path)
        
        if "versions" not in data:
            data["versions"] = {}
        if "metadata" not in data:
            data["metadata"] = {"base_version": None, "latest_version": None}
        
        # Add/update version entry
        from datetime import timezone
        data["versions"][version] = {
            "generated_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            **metadata
        }
        
        # Update metadata
        versions = list(data["versions"].keys())
        if versions:
            if not data["metadata"]["base_version"]:
                data["metadata"]["base_version"] = versions[0]
            # Set latest version (simple: last added, could be improved with semver comparison)
            data["metadata"]["latest_version"] = versions[-1]
        
        return VersionRegistry.save(registry_path, data)
    
    @staticmethod
    def get_versions(registry_path: Path) -> List[str]:
        """Get all registered versions.
        
        Args:
            registry_path: Path to version_registry.json file
            
        Returns:
            List of version strings
        """
        data = VersionRegistry.load(registry_path)
        return list(data.get("versions", {}).keys())
    
    @staticmethod
    def get_latest_version(registry_path: Path) -> Optional[str]:
        """Get latest version from registry.
        
        Args:
            registry_path: Path to version_registry.json file
            
        Returns:
            Latest version string, or None if no versions registered
        """
        data = VersionRegistry.load(registry_path)
        return data.get("metadata", {}).get("latest_version")
    
    @staticmethod
    def get_base_version(registry_path: Path) -> Optional[str]:
        """Get base version from registry.
        
        Args:
            registry_path: Path to version_registry.json file
            
        Returns:
            Base version string, or None if not set
        """
        data = VersionRegistry.load(registry_path)
        return data.get("metadata", {}).get("base_version")
    
    @staticmethod
    def get_base_schema_path(registry_path: Path, version: str) -> Optional[Path]:
        """Get path to base version's schema file if cached.
        
        Args:
            registry_path: Path to version_registry.json file
            version: Version string to get base schema for
            
        Returns:
            Path to cached schema file, or None if not cached
        """
        data = VersionRegistry.load(registry_path)
        version_data = data.get("versions", {}).get(version, {})
        base_version = version_data.get("base_version")
        
        if not base_version:
            return None
        
        # Check if base version has cached schema
        base_version_data = data.get("versions", {}).get(base_version, {})
        schema_url = base_version_data.get("schema_url")
        
        if not schema_url:
            return None
        
        # For file paths, return the path directly
        if not schema_url.startswith(('http://', 'https://')):
            schema_path = Path(schema_url)
            if not schema_path.is_absolute():
                schema_path = Path.cwd() / schema_path
            if schema_path.exists():
                return schema_path
        
        # For URLs, we'd need to fetch, so return None
        return None
    
    @staticmethod
    def save_version_schema(registry_path: Path, version: str, schema: Dict[str, Any]) -> None:
        """Save schema to cache file for later use.
        
        Args:
            registry_path: Path to version_registry.json file
            version: Version string
            schema: Schema dictionary to save
        """
        try:
            # Create cache directory next to registry
            cache_dir = registry_path.parent / ".schema_cache"
            cache_dir.mkdir(exist_ok=True)
            
            # Save schema as JSON
            version_dir = VersionDetector.normalize_for_directory(version)
            cache_file = cache_dir / f"{version_dir}.json"
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(schema, f, indent=2)
            
            logger.debug(f"Cached schema for version {version} at {cache_file}")
        except Exception as e:
            logger.warning(f"Failed to cache schema for version {version}: {e}")
    
    @staticmethod
    def load_version_schema(registry_path: Path, version: str) -> Optional[Dict[str, Any]]:
        """Load schema for a specific version from cache or registry.
        
        Args:
            registry_path: Path to version_registry.json file
            version: Version string to load schema for
            
        Returns:
            Schema dictionary, or None if not available
        """
        # First try to load from cache
        cache_dir = registry_path.parent / ".schema_cache"
        version_dir = VersionDetector.normalize_for_directory(version)
        cache_file = cache_dir / f"{version_dir}.json"
        
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.debug(f"Failed to load cached schema from {cache_file}: {e}")
        
        # Fallback: try to load from original schema_url if it's a local file
        data = VersionRegistry.load(registry_path)
        version_data = data.get("versions", {}).get(version, {})
        schema_url = version_data.get("schema_url")
        
        if not schema_url:
            return None
        
        # Try to load from original file path
        if not schema_url.startswith(('http://', 'https://')):
            schema_path = Path(schema_url)
            if not schema_path.is_absolute():
                schema_path = Path.cwd() / schema_path
            if schema_path.exists():
                try:
                    with open(schema_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    # Try JSON first, then YAML
                    try:
                        return json.loads(content)
                    except json.JSONDecodeError:
                        return yaml.safe_load(content)
                except Exception as e:
                    logger.debug(f"Failed to load schema from {schema_path}: {e}")
        
        # If not cached or file doesn't exist, return None
        # The caller should handle fetching with the original config
        return None

# ============================================================================
# CLIENT GENERATOR
# ============================================================================
class GeneratorRunner:
    """Runs openapi-python-client with retry logic and error handling."""
    
    @staticmethod
    def run(schema_path: Path, output_path: Path, disable_hooks: bool) -> bool:
        """Execute generator with automatic retries.
        
        Args:
            schema_path: Path to OpenAPI schema file
            output_path: Output directory for generated client
            disable_hooks: Whether to disable post-generation hooks
            
        Returns:
            True if generation succeeded, False otherwise
        """
        base_cmd = [
            'openapi-python-client', 'generate', '--path', str(schema_path),
            '--output-path', str(output_path), '--meta', 'none',
            '--overwrite', '--no-fail-on-warning'
        ]
        
        if disable_hooks:
            return GeneratorRunner._run_with_hooks_disabled(base_cmd)
        else:
            return GeneratorRunner._run_default(base_cmd)
    
    @staticmethod
    def _run_with_hooks_disabled(base_cmd: list) -> bool:
        """Run generator with post-hooks disabled.
        
        Args:
            base_cmd: Base command list for generator
            
        Returns:
            True if generation succeeded, False otherwise
        """
        with temp_file({"post_hooks": []}, as_json=False) as config_path:
            cmd = base_cmd + ['--config', str(config_path)]
            result = GeneratorRunner._execute(cmd)
        
        return GeneratorRunner._check_result(result)
    
    @staticmethod
    def _run_default(base_cmd: list) -> bool:
        """Run generator with default settings, retry on ruff failure.
        
        Args:
            base_cmd: Base command list for generator
            
        Returns:
            True if generation succeeded, False otherwise
        """
        result = GeneratorRunner._execute(base_cmd)
        stderr_lower = result.stderr.lower() if result.stderr else ""
        
        # Retry with hooks disabled if ruff failed
        if result.returncode != 0 and 'ruff failed' in stderr_lower:
            logger.warning("Ruff failed, retrying with hooks disabled")
            with temp_file({"post_hooks": []}, as_json=False) as config_path:
                cmd = base_cmd + ['--config', str(config_path)]
                result = GeneratorRunner._execute(cmd)
        
        return GeneratorRunner._check_result(result)
    
    @staticmethod
    def _execute(cmd: list) -> subprocess.CompletedProcess:
        """Execute subprocess command with UI spinner.
        
        Args:
            cmd: Command list to execute
            
        Returns:
            CompletedProcess instance with stdout and stderr
        """
        with console.status("[accent]Generating client...", spinner="bouncingBar"):
            return subprocess.run(cmd, capture_output=True, text=True)
    
    @staticmethod
    def _check_result(result: subprocess.CompletedProcess) -> bool:
        """Check subprocess result and log errors.
        
        Args:
            result: CompletedProcess instance from subprocess.run
            
        Returns:
            True if returncode is 0, False otherwise
        """
        if result.returncode != 0:
            # Log both stderr and stdout for better debugging
            error_msg = result.stderr.strip() if result.stderr else ""
            output_msg = result.stdout.strip() if result.stdout else ""
            
            if error_msg:
                logger.error(f"Generation failed (stderr): {error_msg}")
            if output_msg and output_msg != error_msg:
                logger.error(f"Generation output (stdout): {output_msg}")
            
            if not error_msg and not output_msg:
                logger.error("Generation failed with no output")
        
        return result.returncode == 0

class ClientGenerator:
    """Main orchestrator for client generation."""
    
    def __init__(self, output_base: Path = Path("./clients")):
        self.output_base = output_base
        self.services: Dict[str, ServiceConfig] = {}
    
    def add_service(self, key: str, config: ServiceConfig) -> None:
        """Register service."""
        self.services[key] = config
    
    def generate(self, service_key: str, force: bool = False, version: Optional[str] = None) -> bool:
        """Generate client for service.
        
        Args:
            service_key: Service identifier from configuration
            force: If True, regenerate even if client exists
            version: Optional specific version to generate (for versioned projects)
            
        Returns:
            True if generation succeeded, False otherwise
        """
        config = self.services.get(service_key)
        if not config:
            logger.error(f"Service '{service_key}' not found")
            return False
        
        # Check if versioning is enabled
        if config.versioning and config.versioning.enabled:
            return self._generate_versioned(service_key, config, force, version)
        else:
            return self._generate_single(service_key, config, force)
    
    def _generate_single(self, service_key: str, config: ServiceConfig, force: bool) -> bool:
        """Generate single non-versioned client (original logic).
        
        Args:
            service_key: Service identifier
            config: Service configuration
            force: If True, regenerate even if client exists
            
        Returns:
            True if generation succeeded, False otherwise
        """
        # Safely construct output path
        try:
            output_path = (self.output_base / config.output_dir).resolve()
            
            # Verify output path is within output_base to prevent path traversal
            if not str(output_path).startswith(str(self.output_base.resolve())):
                logger.error(f"Security: Output path escapes base directory: {output_path}")
                return False
        except ValueError as e:
            logger.error(f"Invalid path value for output directory '{config.output_dir}': {e}")
            return False
        except OSError as e:
            logger.error(f"OS error while resolving output path '{config.output_dir}': {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error resolving output path: {e}")
            return False
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if output_path.exists() and not force:
            logger.warning(f"Client exists at {output_path}. Use --force to regenerate")
            return False
        
        # Fetch and process schema
        schema = SchemaProcessor.fetch(config.schema_url, config.request_params, config.prefer_json, config.request_headers)
        if not schema:
            return False
        schema = SchemaProcessor.sanitize_security(schema)
        
        # Clean output directory
        if output_path.exists():
            shutil.rmtree(output_path)
        
        # Generate client
        is_json = config.prefer_json or config.schema_url.lower().endswith('.json')
        with temp_file(schema, as_json=is_json) as schema_path:
            success = GeneratorRunner.run(schema_path, output_path, config.disable_post_hooks)
        
        if not success:
            if output_path.exists() and output_path.is_dir() and not any(output_path.iterdir()):
                output_path.rmdir()
            return False
        
        # Format generated code with Black if enabled
        if config.format_with_black:
            CodeFormatter.format_directory(output_path)
        
        console.print(f":sparkles: [success]Generated[/success] [accent]{service_key}[/accent] → [bold]{output_path}[/bold]")
        return True
    
    def _generate_versioned(self, service_key: str, config: ServiceConfig, force: bool, version: Optional[str] = None) -> bool:
        """Generate versioned clients.
        
        Args:
            service_key: Service identifier
            config: Service configuration with versioning enabled
            force: If True, regenerate even if client exists
            version: Optional specific version to generate (None = all versions or auto-detect)
            
        Returns:
            True if generation succeeded, False otherwise
        """
        # Base output directory for the project
        base_output_path = (self.output_base / config.output_dir).resolve()
        base_output_path.mkdir(parents=True, exist_ok=True)
        
        # Registry path
        registry_path = base_output_path / "version_registry.json"
        
        # Determine which versions to generate
        versions_to_generate = []
        if version:
            # Generate specific version
            if version not in config.versions:
                # If auto_detect is enabled, try to detect and create version config
                if config.versioning.auto_detect:
                    # Use base config or first version config as template
                    template_config = list(config.versions.values())[0] if config.versions else None
                    if template_config:
                        # Fetch schema to detect version
                        schema_url = template_config.input.get('target', '') or config.schema_url
                        schema = SchemaProcessor.fetch(
                            schema_url,
                            template_config.input.get('params', {}) or {},
                            template_config.input.get('prefer_json', False),
                            template_config.input.get('headers', {}) or {}
                        )
                        if schema:
                            detected_version = VersionDetector.detect_from_schema(schema)
                            if detected_version == version:
                                # Create version config from template
                                config.versions[version] = VersionConfig(
                                    version=version,
                                    input=template_config.input.copy(),
                                    output=template_config.output.copy()
                                )
                                versions_to_generate = [version]
                            else:
                                logger.error(f"Version '{version}' not found and auto-detected version is '{detected_version}'")
                                return False
                    else:
                        logger.error(f"Version '{version}' not found in configuration for '{service_key}'")
                        return False
                else:
                    logger.error(f"Version '{version}' not found in configuration for '{service_key}'")
                    return False
            else:
                versions_to_generate = [version]
        else:
            # No version specified
            if config.versioning.auto_detect and not config.versions:
                # Auto-detect version from schema
                # Use base config schema_url or try to find a default
                schema_url = config.schema_url
                if not schema_url and config.versions:
                    # Use first version's schema URL
                    first_version = list(config.versions.values())[0]
                    schema_url = first_version.input.get('target', '')
                
                if schema_url:
                    schema = SchemaProcessor.fetch(
                        schema_url,
                        config.request_params,
                        config.prefer_json,
                        config.request_headers
                    )
                    if schema:
                        detected_version = VersionDetector.detect_from_schema(schema)
                        if detected_version:
                            # Create version config from base config
                            version_config = VersionConfig(
                                version=detected_version,
                                input={
                                    'target': schema_url,
                                    'params': config.request_params,
                                    'headers': config.request_headers,
                                    'prefer_json': config.prefer_json
                                },
                                output={
                                    'base_url': config.base_url,
                                    'package_name': config.package_name,
                                    'format_with_black': config.format_with_black,
                                    'disable_post_hooks': config.disable_post_hooks
                                }
                            )
                            config.versions[detected_version] = version_config
                            versions_to_generate = [detected_version]
                            logger.info(f"Auto-detected version '{detected_version}' from schema")
                        else:
                            logger.warning(f"Could not detect version from schema for '{service_key}'")
                            return False
                    else:
                        logger.error(f"Failed to fetch schema for auto-detection: {schema_url}")
                        return False
                else:
                    logger.error(f"No schema URL available for auto-detection")
                    return False
            else:
                # Generate all configured versions
                versions_to_generate = list(config.versions.keys())
        
        if not versions_to_generate:
            logger.warning(f"No versions to generate for '{service_key}'")
            return False
        
        success_count = 0
        for version_str in versions_to_generate:
            version_config = config.versions[version_str]
            
            # Handle auto-detection if enabled
            if config.versioning.auto_detect:
                # Fetch schema to detect version
                version_schema_url = version_config.input.get('target', '')
                if not version_schema_url:
                    logger.warning(f"No target URL for version '{version_str}', skipping")
                    continue
                
                schema = SchemaProcessor.fetch(
                    version_schema_url,
                    version_config.input.get('params', {}) or {},
                    version_config.input.get('prefer_json', False),
                    version_config.input.get('headers', {}) or {}
                )
                if schema:
                    detected_version = VersionDetector.detect_from_schema(schema)
                    if detected_version and detected_version != version_str:
                        logger.info(f"Auto-detected version '{detected_version}' from schema (config: '{version_str}')")
                        # Use detected version for directory name
                        version_str = detected_version
            
            # Create version directory
            version_dir_name = VersionDetector.normalize_for_directory(version_str)
            version_output_path = base_output_path / version_dir_name
            
            # Check if exists and force flag
            if version_output_path.exists() and not force:
                logger.warning(f"Version '{version_str}' exists at {version_output_path}. Use --force to regenerate")
                continue
            
            # Generate client for this version
            # Fetch schema for registry update
            schema_url = version_config.input.get('target', '')
            schema = None
            if schema_url:
                schema = SchemaProcessor.fetch(
                    schema_url,
                    version_config.input.get('params', {}) or {},
                    version_config.input.get('prefer_json', False),
                    version_config.input.get('headers', {}) or {}
                )
            
            if self._generate_versioned_client(service_key, version_str, version_config, version_output_path, force, config, registry_path):
                success_count += 1
                
                # Update registry
                if schema:
                    openapi_version = schema.get('openapi') or schema.get('swagger', 'unknown')
                    # Extract endpoint signatures (simplified - just method + path)
                    endpoints = []
                    paths = schema.get('paths', {})
                    for path, path_item in paths.items():
                        if isinstance(path_item, dict):
                            for method in SchemaProcessor.HTTP_METHODS:
                                if method in path_item:
                                    endpoints.append(f"{method.upper()} {path}")
                    
                    # Extract model names
                    models = []
                    components = schema.get('components', {})
                    schemas = components.get('schemas', {})
                    if isinstance(schemas, dict):
                        models = list(schemas.keys())
                    
                    # Determine changed endpoints/models if using incremental generation
                    changed_endpoints = []
                    changed_models = []
                    base_version = config.versioning.base_version if config.versioning else None
                    generation_mode = config.versioning.generation_mode if config.versioning else "full"
                    
                    if generation_mode == "changed" and base_version and version_str != base_version:
                        # Load base schema for comparison
                        base_schema = VersionRegistry.load_version_schema(registry_path, base_version)
                        if not base_schema:
                            base_version_config = config.versions.get(base_version)
                            if base_version_config:
                                base_schema_url = base_version_config.input.get('target', '')
                                if base_schema_url:
                                    base_schema = SchemaProcessor.fetch(
                                        base_schema_url,
                                        base_version_config.input.get('params', {}) or {},
                                        base_version_config.input.get('prefer_json', False),
                                        base_version_config.input.get('headers', {}) or {}
                                    )
                        
                        if base_schema:
                            endpoint_changes = SchemaComparator.compare_endpoints(base_schema, schema)
                            model_changes = SchemaComparator.compare_models(base_schema, schema)
                            changed_endpoints = endpoint_changes['new'] + endpoint_changes['modified']
                            changed_models = model_changes['new'] + model_changes['modified']
                    
                    VersionRegistry.add_version(
                        registry_path,
                        version_str,
                        {
                            "openapi_version": str(openapi_version),
                            "schema_url": schema_url,
                            "endpoints": endpoints,
                            "endpoint_count": len(endpoints),
                            "models": models,
                            "changed_endpoints": changed_endpoints,
                            "changed_models": changed_models,
                            "base_version": base_version if version_str != base_version else None
                        }
                    )
        
        # Generate main entry point if all versions succeeded
        if success_count > 0:
            self._generate_versioned_entry_point(service_key, config, base_output_path)
        
        if success_count == len(versions_to_generate):
            console.print(f":sparkles: [success]Generated[/success] [accent]{service_key}[/accent] ({success_count} version(s)) → [bold]{base_output_path}[/bold]")
            return True
        elif success_count > 0:
            console.print(f":warning: [warning]Partially generated[/warning] [accent]{service_key}[/accent] ({success_count}/{len(versions_to_generate)} versions)")
            return True
        else:
            return False
    
    def _generate_versioned_client(self, service_key: str, version: str, version_config: VersionConfig, 
                                   output_path: Path, force: bool, config: ServiceConfig, registry_path: Path) -> bool:
        """Generate client for a specific version.
        
        Args:
            service_key: Service identifier
            version: Version string
            version_config: Version configuration
            output_path: Output directory for this version
            force: If True, regenerate even if exists
            config: Service configuration (for accessing versioning config)
            registry_path: Path to version registry
            
        Returns:
            True if generation succeeded, False otherwise
        """
        schema_url = version_config.input.get('target', '')
        if not schema_url:
            logger.error(f"No target URL for version '{version}'")
            return False
        
        # Fetch and process schema
        schema = SchemaProcessor.fetch(
            schema_url,
            version_config.input.get('params', {}) or {},
            version_config.input.get('prefer_json', False),
            version_config.input.get('headers', {}) or {}
        )
        if not schema:
            return False
        schema = SchemaProcessor.sanitize_security(schema)
        
        # Check generation mode
        generation_mode = config.versioning.generation_mode if config.versioning else "full"
        base_version = config.versioning.base_version if config.versioning else None
        
        # Determine if this is the base version
        is_base_version = (base_version and version == base_version) or (
            not base_version and version == VersionRegistry.get_base_version(registry_path)
        )
        
        # Use incremental generation if mode is "changed" and not base version
        if generation_mode == "changed" and not is_base_version and base_version:
            logger.info(f"Using incremental generation for version '{version}' (base: '{base_version}')")
            return self._generate_incremental_client(
                service_key, version, version_config, output_path, force,
                schema, base_version, config, registry_path
            )
        else:
            # Use full generation
            if generation_mode == "changed" and is_base_version:
                logger.info(f"Base version '{version}' always uses full generation mode (ignoring 'changed' mode)")
            
            # Clean output directory
            if output_path.exists():
                shutil.rmtree(output_path)
            
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Generate client
            is_json = version_config.input.get('prefer_json', False) or schema_url.lower().endswith('.json')
            with temp_file(schema, as_json=is_json) as schema_path:
                success = GeneratorRunner.run(schema_path, output_path, version_config.output.get('disable_post_hooks', True))
            
            if not success:
                if output_path.exists() and output_path.is_dir() and not any(output_path.iterdir()):
                    output_path.rmdir()
                return False
            
            # Format generated code with Black if enabled
            if version_config.output.get('format_with_black', True):
                CodeFormatter.format_directory(output_path)
            
            # Save schema to cache if this is the base version (for incremental generation)
            if is_base_version:
                VersionRegistry.save_version_schema(registry_path, version, schema)
            
            logger.info(f"Generated version '{version}' → {output_path}")
            return True
    
    def _generate_incremental_client(self, service_key: str, version: str, version_config: VersionConfig,
                                     output_path: Path, force: bool, new_schema: Dict[str, Any],
                                     base_version: str, config: ServiceConfig, registry_path: Path) -> bool:
        """Generate incremental client with only changed endpoints/models.
        
        Args:
            service_key: Service identifier
            version: Version string
            version_config: Version configuration
            output_path: Output directory for this version
            force: If True, regenerate even if exists
            new_schema: New version schema
            base_version: Base version string
            config: Service configuration
            registry_path: Path to version registry
            
        Returns:
            True if generation succeeded, False otherwise
        """
        # Load base version schema
        base_schema = VersionRegistry.load_version_schema(registry_path, base_version)
        
        if not base_schema:
            # Try to fetch base version schema from config
            base_version_config = config.versions.get(base_version)
            if base_version_config:
                base_schema_url = base_version_config.input.get('target', '')
                if base_schema_url:
                    base_schema = SchemaProcessor.fetch(
                        base_schema_url,
                        base_version_config.input.get('params', {}) or {},
                        base_version_config.input.get('prefer_json', False),
                        base_version_config.input.get('headers', {}) or {}
                    )
                    if base_schema:
                        base_schema = SchemaProcessor.sanitize_security(base_schema)
        
        if not base_schema:
            logger.warning(f"Could not load base version '{base_version}' schema, falling back to full generation")
            # Fallback to full generation
            if output_path.exists():
                shutil.rmtree(output_path)
            output_path.mkdir(parents=True, exist_ok=True)
            is_json = version_config.input.get('prefer_json', False) or version_config.input.get('target', '').lower().endswith('.json')
            with temp_file(new_schema, as_json=is_json) as schema_path:
                success = GeneratorRunner.run(schema_path, output_path, version_config.output.get('disable_post_hooks', True))
            if success and version_config.output.get('format_with_black', True):
                CodeFormatter.format_directory(output_path)
            return success
        
        # Compare schemas to detect changes
        endpoint_changes = SchemaComparator.compare_endpoints(base_schema, new_schema)
        model_changes = SchemaComparator.compare_models(base_schema, new_schema)
        
        # Log change detection results
        logger.info(f"Change detection for version '{version}':")
        logger.info(f"  Endpoints - New: {len(endpoint_changes['new'])}, Modified: {len(endpoint_changes['modified'])}, "
                   f"Unchanged: {len(endpoint_changes['unchanged'])}, Removed: {len(endpoint_changes['removed'])}")
        logger.info(f"  Models - New: {len(model_changes['new'])}, Modified: {len(model_changes['modified'])}, "
                   f"Unchanged: {len(model_changes['unchanged'])}")
        
        # Filter schema to include only changed endpoints/models and dependencies
        filtered_schema = self._filter_schema_for_changes(
            new_schema, endpoint_changes, model_changes, base_schema
        )
        
        # Clean output directory
        if output_path.exists():
            shutil.rmtree(output_path)
        
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Generate client with filtered schema
        schema_url = version_config.input.get('target', '')
        is_json = version_config.input.get('prefer_json', False) or schema_url.lower().endswith('.json')
        with temp_file(filtered_schema, as_json=is_json) as schema_path:
            success = GeneratorRunner.run(schema_path, output_path, version_config.output.get('disable_post_hooks', True))
        
        if not success:
            if output_path.exists() and output_path.is_dir() and not any(output_path.iterdir()):
                output_path.rmdir()
            return False
        
        # Generate import stubs for unchanged endpoints/models
        self._generate_import_stubs(
            output_path, base_version, endpoint_changes, model_changes
        )
        
        # Format generated code with Black if enabled
        if version_config.output.get('format_with_black', True):
            CodeFormatter.format_directory(output_path)
        
        logger.info(f"Generated incremental version '{version}' → {output_path}")
        return True
    
    def _filter_schema_for_changes(self, new_schema: Dict[str, Any], endpoint_changes: Dict[str, Any],
                                   model_changes: Dict[str, Any], base_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Filter schema to include only changed endpoints/models and their dependencies.
        
        Args:
            new_schema: Full new version schema
            endpoint_changes: Change detection results for endpoints
            model_changes: Change detection results for models
            base_schema: Base version schema for dependency resolution
            
        Returns:
            Filtered schema dictionary
        """
        filtered = {
            'openapi': new_schema.get('openapi', '3.0.0'),
            'info': new_schema.get('info', {}),
            'servers': new_schema.get('servers', []),
            'paths': {},
            'components': {
                'schemas': {},
                'parameters': new_schema.get('components', {}).get('parameters', {}),
                'responses': new_schema.get('components', {}).get('responses', {}),
                'securitySchemes': new_schema.get('components', {}).get('securitySchemes', {})
            }
        }
        
        # Get changed endpoint signatures
        changed_endpoints = set(endpoint_changes['new'] + endpoint_changes['modified'])
        
        # Filter paths to include only changed endpoints
        new_paths = new_schema.get('paths', {})
        for path, path_item in new_paths.items():
            if not isinstance(path_item, dict):
                continue
            
            filtered_path_item = {}
            for method in SchemaProcessor.HTTP_METHODS:
                if method in path_item:
                    signature = SchemaComparator.get_endpoint_signature(path, method)
                    if signature in changed_endpoints:
                        filtered_path_item[method] = path_item[method]
            
            # Include path if it has any changed endpoints
            if filtered_path_item:
                # Preserve path-level parameters and other properties
                filtered_path_item.update({
                    k: v for k, v in path_item.items()
                    if k not in SchemaProcessor.HTTP_METHODS
                })
                filtered['paths'][path] = filtered_path_item
        
        # Collect all model references from changed endpoints
        referenced_models = set()
        for path, path_item in filtered['paths'].items():
            for method, operation in path_item.items():
                if method not in SchemaProcessor.HTTP_METHODS:
                    continue
                if not isinstance(operation, dict):
                    continue
                
                # Extract schema references from request body
                request_body = operation.get('requestBody', {})
                if isinstance(request_body, dict):
                    content = request_body.get('content', {})
                    for content_type, media_type in content.items():
                        if isinstance(media_type, dict):
                            schema_ref = media_type.get('schema', {})
                            referenced_models.update(self._extract_schema_refs(schema_ref))
                
                # Extract schema references from responses
                responses = operation.get('responses', {})
                for status, response in responses.items():
                    if isinstance(response, dict):
                        content = response.get('content', {})
                        for content_type, media_type in content.items():
                            if isinstance(media_type, dict):
                                schema_ref = media_type.get('schema', {})
                                referenced_models.update(self._extract_schema_refs(schema_ref))
                
                # Extract schema references from parameters
                parameters = operation.get('parameters', [])
                for param in parameters:
                    if isinstance(param, dict):
                        schema_ref = param.get('schema', {})
                        referenced_models.update(self._extract_schema_refs(schema_ref))
        
        # Include changed models and all referenced models
        changed_models = set(model_changes['new'] + model_changes['modified'])
        models_to_include = changed_models | referenced_models
        
        # Filter components.schemas
        new_schemas = new_schema.get('components', {}).get('schemas', {})
        if isinstance(new_schemas, dict):
            for model_name, model_schema in new_schemas.items():
                if model_name in models_to_include:
                    filtered['components']['schemas'][model_name] = model_schema
        
        return filtered
    
    def _extract_schema_refs(self, schema: Dict[str, Any]) -> set:
        """Extract all schema references from a schema object.
        
        Args:
            schema: Schema dictionary
            
        Returns:
            Set of schema reference names (without #/components/schemas/ prefix)
        """
        refs = set()
        
        if not isinstance(schema, dict):
            return refs
        
        # Check for direct $ref
        ref = schema.get('$ref', '')
        if ref and ref.startswith('#/components/schemas/'):
            model_name = ref.replace('#/components/schemas/', '')
            refs.add(model_name)
        
        # Check for allOf, anyOf, oneOf
        for key in ['allOf', 'anyOf', 'oneOf']:
            if key in schema and isinstance(schema[key], list):
                for item in schema[key]:
                    if isinstance(item, dict):
                        refs.update(self._extract_schema_refs(item))
        
        # Check for items (arrays)
        if 'items' in schema and isinstance(schema['items'], dict):
            refs.update(self._extract_schema_refs(schema['items']))
        
        # Check for properties (objects)
        if 'properties' in schema and isinstance(schema['properties'], dict):
            for prop_schema in schema['properties'].values():
                if isinstance(prop_schema, dict):
                    refs.update(self._extract_schema_refs(prop_schema))
        
        # Check for additionalProperties
        if 'additionalProperties' in schema:
            if isinstance(schema['additionalProperties'], dict):
                refs.update(self._extract_schema_refs(schema['additionalProperties']))
        
        return refs
    
    def _generate_import_stubs(self, output_path: Path, base_version: str,
                               endpoint_changes: Dict[str, Any], model_changes: Dict[str, Any]) -> None:
        """Generate import stubs for unchanged endpoints/models from base version.
        
        Args:
            output_path: Output directory for this version
            base_version: Base version string
            endpoint_changes: Change detection results for endpoints
            model_changes: Change detection results for models
        """
        base_version_import = VersionDetector.normalize_for_import(base_version)
        
        # Group unchanged endpoints by module
        unchanged_endpoints = endpoint_changes.get('unchanged', [])
        endpoint_modules = {}
        
        for endpoint_sig in unchanged_endpoints:
            # Parse endpoint signature: "METHOD /api/module/endpoint"
            parts = endpoint_sig.split(' ', 1)
            if len(parts) != 2:
                continue
            path = parts[1]
            
            # Extract module name from path (e.g., /api/user -> user)
            path_parts = [p for p in path.split('/') if p and p != 'api']
            if path_parts:
                module_name = path_parts[0]
                if module_name not in endpoint_modules:
                    endpoint_modules[module_name] = []
                endpoint_modules[module_name].append(endpoint_sig)
        
        # Generate __init__.py files for unchanged endpoint modules
        # Only create stubs in directories that already exist (from changed endpoints)
        # This keeps the structure clean - we don't create empty directories
        api_dir = output_path / 'api'
        if api_dir.exists():
            for module_name, endpoints in endpoint_modules.items():
                module_dir = api_dir / module_name
                # Only create import stub if directory already exists (has changed endpoints)
                if module_dir.exists():
                    init_file = module_dir / '__init__.py'
                    import_line = f"from ...{base_version_import}.api.{module_name} import *\n"
                    
                    # Append import if file exists, otherwise create
                    if init_file.exists():
                        with open(init_file, 'r', encoding='utf-8') as f:
                            content = f.read()
                        if import_line.strip() not in content:
                            with open(init_file, 'a', encoding='utf-8') as f:
                                # Add newline if file doesn't end with one
                                if content and not content.endswith('\n'):
                                    f.write('\n')
                                f.write(import_line)
                    else:
                        with open(init_file, 'w', encoding='utf-8') as f:
                            f.write(import_line)
        
        # Generate imports for unchanged models
        unchanged_models = model_changes.get('unchanged', [])
        if unchanged_models:
            models_dir = output_path / 'models'
            if models_dir.exists():
                init_file = models_dir / '__init__.py'
                
                # Create import statement
                if len(unchanged_models) > 10:
                    # Use * import if too many models
                    import_line = f"from ...{base_version_import}.models import *\n"
                else:
                    # Import specific models
                    model_names = ', '.join(unchanged_models)
                    import_line = f"from ...{base_version_import}.models import {model_names}\n"
                
                # Append import if file exists, otherwise create
                if init_file.exists():
                    with open(init_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    if import_line.strip() not in content:
                        with open(init_file, 'a', encoding='utf-8') as f:
                            # Add newline if file doesn't end with one
                            if content and not content.endswith('\n'):
                                f.write('\n')
                            f.write(import_line)
                else:
                    with open(init_file, 'w', encoding='utf-8') as f:
                        f.write(import_line)
    
    def _generate_versioned_entry_point(self, service_key: str, config: ServiceConfig, base_output_path: Path) -> None:
        """Generate __init__.py with version selector and factory function.
        
        Args:
            service_key: Service identifier
            config: Service configuration
            base_output_path: Base output directory for the project
        """
        registry_path = base_output_path / "version_registry.json"
        versions = VersionRegistry.get_versions(registry_path)
        
        if not versions:
            return
        
        # Generate version map using importlib for dynamic imports
        # (Python can't import from directories starting with numbers)
        version_dir_map = []
        
        for version_str in versions:
            version_dir = VersionDetector.normalize_for_directory(version_str)
            version_dir_map.append(f'    "{version_str}": "{version_dir}",')
        
        # Get latest version for default
        latest_version = VersionRegistry.get_latest_version(registry_path) or versions[-1]
        
        # Get base_url from version configs if available
        default_base_url = config.base_url
        if not default_base_url and versions:
            # Try to get base_url from first version config
            first_version = versions[0]
            if first_version in config.versions:
                default_base_url = config.versions[first_version].output.get('base_url', '')
        
        # Generate __init__.py content using importlib for dynamic imports
        init_content = f'''"""Generated API client for {service_key}.

This module provides versioned clients for the {config.name} API.
Use get_client() to obtain a client instance for a specific version.
"""

import importlib
import sys
from pathlib import Path

# Version to directory mapping
_VERSION_DIRS = {{
{chr(10).join(version_dir_map)}
}}

def get_client(version: str = "{latest_version}", base_url: str = None, **kwargs):
    """Get client for specific version.
    
    Args:
        version: API version string (default: "{latest_version}")
        base_url: Base URL for the API (optional, uses default from config)
        **kwargs: Additional arguments passed to AuthenticatedClient
        
    Returns:
        AuthenticatedClient instance for the specified version
        
    Raises:
        ValueError: If version is not found
        ImportError: If the version module cannot be imported
    """
    if version not in _VERSION_DIRS:
        available_versions = ", ".join(_VERSION_DIRS.keys())
        raise ValueError(f"Version {{version}} not found. Available versions: {{available_versions}}")
    
    # Get the directory name for this version
    version_dir = _VERSION_DIRS[version]
    
    # Dynamically import the client module using importlib
    # Since directory names may start with numbers, we need to use the full path
    current_module = sys.modules[__name__]
    package_path = Path(current_module.__file__).parent
    version_module_path = package_path / version_dir / "client.py"
    
    if not version_module_path.exists():
        raise ImportError(f"Client module not found for version {{version}} at {{version_module_path}}")
    
    # Use importlib to load the module
    spec = importlib.util.spec_from_file_location(
        f"{{__name__}}.{{version_dir}}.client",
        version_module_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to load client module for version {{version}}")
    
    client_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client_module)
    
    # Get the AuthenticatedClient class
    client_class = getattr(client_module, "AuthenticatedClient", None)
    if client_class is None:
        raise ImportError(f"AuthenticatedClient not found in module for version {{version}}")
    
    # Use base_url from config if not provided
    if base_url is None:
        base_url = "{default_base_url}" if "{default_base_url}" else None
    
    return client_class(base_url=base_url, **kwargs)


__all__ = ["get_client"]
'''
        
        # Write __init__.py
        init_path = base_output_path / "__init__.py"
        try:
            with open(init_path, 'w', encoding='utf-8') as f:
                f.write(init_content)
            logger.debug(f"Generated entry point: {init_path}")
        except IOError as e:
            logger.warning(f"Failed to generate entry point: {e}")
    
    def generate_all(self, force: bool = False) -> int:
        """Generate all clients with progress bar.
        
        Args:
            force: If True, regenerate even if client exists
            
        Returns:
            Number of successfully generated clients
        """
        if not self.services:
            logger.warning("No services configured - nothing to generate")
            return 0
        
        total, success_count = len(self.services), 0
        
        with Progress(SpinnerColumn(style="accent"), TextColumn("[accent]Generating[/accent]"),
                     BarColumn(bar_width=None), TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                     TimeElapsedColumn(), console=console, transient=True) as progress:
            task_id = progress.add_task("generate_all", total=total)
            for key in self.services:
                if self.generate(key, force):
                    success_count += 1
                progress.advance(task_id, 1)
        
        console.print(f"[success]✓ Generated {success_count}/{total} clients")
        return success_count
    
    def list_services(self) -> None:
        """Display all services."""
        if not self.services:
            console.print(Panel.fit("No services configured", title="Services", style="warning"))
            return
        
        table = Table(title="Configured Services", box=box.ROUNDED, show_lines=False)
        table.add_column("Status", style="success", no_wrap=True)
        table.add_column("Key", style="accent")
        table.add_column("Name", style="info")
        table.add_column("Schema URL", style="dim")
        table.add_column("Versions", style="dim", no_wrap=True)
        
        for key, config in self.services.items():
            base_path = self.output_base / config.output_dir
            status = "✓" if base_path.exists() else "○"
            
            # Show version information if versioning is enabled
            version_info = ""
            if config.versioning and config.versioning.enabled:
                registry_path = base_path / "version_registry.json"
                versions = VersionRegistry.get_versions(registry_path)
                if versions:
                    latest = VersionRegistry.get_latest_version(registry_path) or versions[-1]
                    version_info = f"{len(versions)} version(s), latest: {latest}"
                else:
                    version_info = f"{len(config.versions)} configured"
            
            table.add_row(status, key, config.name, config.schema_url, version_info)
        console.print(table)
    
    def list_versions(self, service_key: str) -> None:
        """List all versions for a service."""
        config = self.services.get(service_key)
        if not config:
            console.print(Panel.fit(f"Service '[bold]{service_key}[/bold]' not found", 
                                   title="Error", style="error"))
            return
        
        base_path = self.output_base / config.output_dir
        registry_path = base_path / "version_registry.json"
        
        if not config.versioning or not config.versioning.enabled:
            console.print(Panel.fit(f"Service '[bold]{service_key}[/bold]' does not have versioning enabled", 
                                   title="Info", style="info"))
            return
        
        versions = VersionRegistry.get_versions(registry_path)
        if not versions:
            console.print(Panel.fit(f"No versions generated for '[bold]{service_key}[/bold]' yet", 
                                   title="Info", style="info"))
            return
        
        table = Table(title=f"Versions for {service_key}", box=box.ROUNDED, show_lines=False)
        table.add_column("Version", style="accent")
        table.add_column("Status", style="success", no_wrap=True)
        table.add_column("Generated", style="dim")
        table.add_column("Endpoints", style="dim", justify="right")
        table.add_column("OpenAPI", style="dim")
        
        registry_data = VersionRegistry.load(registry_path)
        for version_str in sorted(versions):
            version_data = registry_data.get("versions", {}).get(version_str, {})
            version_path = base_path / VersionDetector.normalize_for_directory(version_str)
            status = "✓" if version_path.exists() else "○"
            
            generated_at = version_data.get("generated_at", "Unknown")
            if generated_at != "Unknown":
                try:
                    dt = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
                    generated_at = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            
            endpoint_count = version_data.get("endpoint_count", 0)
            openapi_version = version_data.get("openapi_version", "unknown")
            
            table.add_row(version_str, status, generated_at, str(endpoint_count), openapi_version)
        
        console.print(table)
    
    def info(self, service_key: str) -> None:
        """Show service details."""
        config = self.services.get(service_key)
        if not config:
            console.print(Panel.fit(f"Service '[bold]{service_key}[/bold]' not found", 
                                   title="Error", style="error"))
            return
        
        output_path = self.output_base / config.output_dir
        exists = output_path.exists()
        
        grid = Table.grid(padding=(0, 1))
        grid.add_column(justify="right", style="dim")
        grid.add_column()
        grid.add_row("Name", config.name)
        grid.add_row("Schema URL", config.schema_url)
        grid.add_row("Base URL", config.base_url)
        if config.original_base_url and config.original_base_url != config.base_url:
            grid.add_row("Original Base URL", config.original_base_url or "(auto-detected)")
        grid.add_row("Output", str(output_path))
        grid.add_row("Status", "Generated ✓" if exists else "Not generated")
        
        if exists:
            mtime = datetime.fromtimestamp(output_path.stat().st_mtime)
            grid.add_row("Modified", mtime.strftime('%Y-%m-%d %H:%M:%S'))
        
        console.print(Panel(grid, title=f"Service: [accent]{service_key}[/accent]", box=box.ROUNDED))

# ============================================================================
# BUILDER PATTERN - Config Loading
# ============================================================================
class ConfigLoader:
    """Loads and parses configuration files."""
    
    @staticmethod
    def load(generator: ClientGenerator, config_file: str) -> bool:
        """Load services from config file."""
        config_path = Path(config_file)
        
        if not config_path.exists():
            logger.error(f"Config file not found: {config_file}")
            logger.error(f"Please create '{config_file}' in current directory")
            return False
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = substitute_recursive(json.load(f))
        except FileNotFoundError:
            logger.error(f"Config file not found: {config_file}")
            return False
        except PermissionError:
            logger.error(f"Permission denied reading config file: {config_file}")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file (line {e.lineno}, col {e.colno}): {e.msg}")
            return False
        except UnicodeDecodeError as e:
            logger.error(f"Invalid encoding in config file (expected UTF-8): {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error loading config: {type(e).__name__}: {e}")
            return False
        
        if 'output_dir' in config_data:
            generator.output_base = Path(config_data['output_dir'])
        
        services_loaded = (ConfigLoader._load_projects(generator, config_data.get('projects', {})) +
                          ConfigLoader._load_services(generator, config_data.get('services', [])))
        
        if services_loaded == 0:
            logger.error("No services found in config")
            return False
        
        logger.info(f"✓ Loaded {services_loaded} services from {config_file}")
        return True
    
    @staticmethod
    def _load_projects(generator: ClientGenerator, projects: Dict[str, Any]) -> int:
        """Load Orval-style projects with optional versioning support.
        
        Args:
            generator: ClientGenerator instance to register services with
            projects: Dictionary mapping project keys to their configurations
            
        Returns:
            Number of projects successfully loaded
        """
        count = 0
        for key, proj in projects.items():
            if not isinstance(proj, dict):
                continue
            
            # Check if versioning is enabled
            versioning_cfg = proj.get('versioning', {})
            versioning_enabled = bool(versioning_cfg.get('enabled', False))
            
            if versioning_enabled:
                # Load versioned project
                try:
                    generation_mode = versioning_cfg.get('generation_mode', 'full')
                    # Validate generation_mode
                    if generation_mode and generation_mode.lower() not in ("full", "changed"):
                        logger.warning(f"Invalid generation_mode '{generation_mode}' for project '{key}', using 'full'")
                        generation_mode = "full"
                    else:
                        generation_mode = generation_mode.lower() if generation_mode else "full"
                    
                    base_version = versioning_cfg.get('base_version')
                    # Note: Base version will be forced to full mode during generation,
                    # but we keep the generation_mode as "changed" for non-base versions
                    
                    versioning = VersioningConfig(
                        enabled=True,
                        auto_detect=bool(versioning_cfg.get('auto_detect', False)),
                        base_version=base_version,
                        generation_mode=generation_mode
                    )
                    
                    # Load version-specific configs
                    versions_dict = proj.get('versions', {})
                    versions = {}
                    for version_str, version_data in versions_dict.items():
                        if not isinstance(version_data, dict):
                            continue
                        version_input = version_data.get('input', {}) or {}
                        version_output = version_data.get('output', {}) or {}
                        
                        versions[version_str] = VersionConfig(
                            version=version_str,
                            input=version_input,
                            output=version_output
                        )
                    
                    # Create base config from first version or use defaults
                    # For versioned projects, we'll use the project key as base output_dir
                    # Individual versions will be in subdirectories
                    first_version = list(versions.values())[0] if versions else None
                    if first_version:
                        base_input = first_version.input
                        base_output = first_version.output
                    else:
                        base_input = {}
                        base_output = {}
                    
                    config = ServiceConfig(
                        name=base_output.get('name', key),
                        schema_url=base_input.get('target', ''),
                        output_dir=base_output.get('dir', key),
                        base_url=base_output.get('base_url', ''),
                        package_name=base_output.get('package_name', ''),
                        request_params=base_input.get('params', {}) or {},
                        request_headers=base_input.get('headers', {}) or {},
                        prefer_json=bool(base_input.get('prefer_json', False)),
                        disable_post_hooks=bool(base_output.get('disable_post_hooks', True)),
                        format_with_black=bool(base_output.get('format_with_black', True)),
                        versioning=versioning,
                        versions=versions
                    )
                    generator.add_service(key, config)
                    count += 1
                except (ValueError, KeyError) as e:
                    logger.warning(f"Skipping invalid versioned project '{key}': {e}")
            else:
                # Load non-versioned project (backward compatible)
                input_cfg = proj.get('input', {}) or {}
                output_cfg = proj.get('output', {}) or {}
                
                try:
                    config = ServiceConfig(
                        name=output_cfg.get('name', key),
                        schema_url=input_cfg.get('target', ''),
                        output_dir=output_cfg.get('dir', key),
                        base_url=output_cfg.get('base_url', ''),
                        package_name=output_cfg.get('package_name', ''),
                        request_params=input_cfg.get('params', {}) or {},
                        request_headers=input_cfg.get('headers', {}) or {},
                        prefer_json=bool(input_cfg.get('prefer_json', False)),
                        disable_post_hooks=bool(output_cfg.get('disable_post_hooks', True)),
                        format_with_black=bool(output_cfg.get('format_with_black', True)),
                    )
                    generator.add_service(key, config)
                    count += 1
                except ValueError as e:
                    logger.warning(f"Skipping invalid project '{key}': {e}")
        return count
    
    @staticmethod
    def _load_services(generator: ClientGenerator, services: List[Dict[str, Any]]) -> int:
        """Load legacy services format.
        
        Args:
            generator: ClientGenerator instance to register services with
            services: List of service configuration dictionaries
            
        Returns:
            Number of services successfully loaded
        """
        count = 0
        for service in services:
            key = service.get('key')
            if not key:
                logger.warning("Skipping service without 'key' field")
                continue
            try:
                config = ServiceConfig(
                    name=service.get('name', key),
                    schema_url=service.get('schema_url', ''),
                    output_dir=service.get('output_dir', key),
                    base_url=service.get('base_url', ''),
                    package_name=service.get('package_name', ''),
                    request_params=service.get('request_params', {}) or {},
                    request_headers=service.get('request_headers', {}) or {},
                    prefer_json=bool(service.get('prefer_json', False)),
                    disable_post_hooks=bool(service.get('disable_post_hooks', True)),
                    format_with_black=bool(service.get('format_with_black', True)),
                )
                generator.add_service(key, config)
                count += 1
            except ValueError as e:
                logger.warning(f"Skipping invalid service '{key}': {e}")
        return count

# ============================================================================
# COMMAND PATTERN - CLI Commands
# ============================================================================
class Command(ABC):
    """Base command interface."""
    @abstractmethod
    def execute(self, generator: ClientGenerator, args: list) -> None:
        pass

class ListCommand(Command):
    """List services command."""
    def execute(self, generator: ClientGenerator, args: list) -> None:
        generator.list_services()

class GenerateCommand(Command):
    """Generate single service command."""
    def execute(self, generator: ClientGenerator, args: list) -> None:
        if len(args) < 2:
            console.print(Panel.fit("Missing service name. Usage: oasist generate <service> [--version <version>]", 
                                   title="Error", style="error"))
            return
        
        # Parse --version flag
        version = None
        force = '--force' in args
        
        # Find --version flag and its value
        try:
            version_idx = args.index('--version')
            if version_idx + 1 < len(args):
                version = args[version_idx + 1]
        except ValueError:
            pass  # --version not found, use None
        
        generator.generate(args[1], force, version)

class GenerateAllCommand(Command):
    """Generate all services command."""
    def execute(self, generator: ClientGenerator, args: list) -> None:
        generator.generate_all('--force' in args)

class InfoCommand(Command):
    """Show service info command."""
    def execute(self, generator: ClientGenerator, args: list) -> None:
        if len(args) < 2:
            console.print(Panel.fit("Missing service name. Usage: oasist info <service>", 
                                   title="Error", style="error"))
            return
        generator.info(args[1])

class VersionsCommand(Command):
    """List versions for a service command."""
    def execute(self, generator: ClientGenerator, args: list) -> None:
        if len(args) < 2:
            console.print(Panel.fit("Missing service name. Usage: oasist versions <service>", 
                                   title="Error", style="error"))
            return
        generator.list_versions(args[1])

class CommandRegistry:
    """Registry for CLI commands."""
    _commands = {
        CMD_LIST: ListCommand(),
        CMD_GENERATE: GenerateCommand(),
        CMD_GENERATE_ALL: GenerateAllCommand(),
        CMD_INFO: InfoCommand(),
        CMD_VERSIONS: VersionsCommand(),
    }
    
    @staticmethod
    def execute(command: str, generator: ClientGenerator, args: list) -> bool:
        """Execute command if registered."""
        cmd = CommandRegistry._commands.get(command)
        if cmd:
            cmd.execute(generator, args)
            return True
        return False

# ============================================================================
# CLI HELP
# ============================================================================
class HelpDisplay:
    """Displays help information."""
    
    @staticmethod
    def show_main():
        """Show main help."""
        help_text = [
            ("[bold]USAGE[/bold]", "oasist [global-options] <command> [options]"),
            ("", ""),
            ("[bold]GLOBAL OPTIONS[/bold]", ""),
            ("--config, -c <file>", "Config file path (default: oasist_config.json)"),
            ("--verbose, -v", "Enable verbose/debug logging"),
            ("", ""),
            ("[bold]COMMANDS[/bold]", ""),
            ("list", "List all services and status"),
            ("generate <service>", "Generate client for service"),
            ("generate-all", "Generate all clients"),
            ("info <service>", "Show service details"),
            ("versions <service>", "List all versions for a service"),
            ("help [command]", "Show help"),
            ("", ""),
            ("[bold]OPTIONS[/bold]", ""),
            ("--help, -h", "Show help"),
            ("--version, -V", "Show version"),
            ("--force", "Regenerate existing clients"),
            ("--version <version>", "Generate specific version (for versioned projects)"),
            ("", ""),
            ("[bold]EXAMPLES[/bold]", ""),
            ("oasist list", "List services"),
            ("oasist -v generate myapi", "Generate with verbose output"),
            ("oasist -c prod.json generate myapi", "Use custom config"),
            ("oasist generate myapi --force", "Force regenerate"),
            ("oasist generate myapi --version 1.1.0", "Generate specific version"),
            ("oasist generate-all", "Generate all"),
            ("oasist info myapi", "Show service info"),
            ("oasist versions myapi", "List versions for service"),
        ]
        
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="accent")
        grid.add_column()
        for col1, col2 in help_text:
            grid.add_row(col1, col2)
        
        console.print(Panel(grid, title="OASist Client Generator", box=box.ROUNDED))
    
    @staticmethod
    def show_command(command: str):
        """Show command-specific help."""
        help_details = {
            'list': ('List configured services', 'oasist list', None),
            'generate': ('Generate client for service', 'oasist generate <service> [--version <version>] [--force]', 
                        ['--version <version>: Generate specific version (for versioned projects)',
                         '--force: Regenerate if exists']),
            'generate-all': ('Generate all clients', 'oasist generate-all [--force]', 
                           ['--force: Regenerate if exists']),
            'info': ('Show service details', 'oasist info <service>', None),
            'versions': ('List all versions for a service', 'oasist versions <service>', None),
        }
        
        if command not in help_details:
            HelpDisplay.show_main()
            return
        
        desc, usage, options = help_details[command]
        grid = Table.grid(padding=(0, 1))
        grid.add_column()
        grid.add_row(f"[bold]{command}[/bold]")
        grid.add_row("")
        grid.add_row(desc)
        grid.add_row("")
        grid.add_row("[bold]USAGE[/bold]")
        grid.add_row(usage)
        
        if options:
            grid.add_row("")
            grid.add_row("[bold]OPTIONS[/bold]")
            for opt in options:
                grid.add_row(f"  {opt}")
        
        console.print(Panel(grid, title="Command Help", box=box.ROUNDED))

# ============================================================================
# MAIN CLI ENTRY
# ============================================================================
def parse_args(args: List[str]) -> tuple:
    """Parse command line arguments.
    
    Args:
        args: List of command line arguments
        
    Returns:
        Tuple of (config_file, verbose, remaining_args)
    """
    config_file = CONFIG_FILE
    verbose = False
    remaining = []
    i = 0
    
    while i < len(args):
        arg = args[i]
        if arg in ['--config', '-c'] and i + 1 < len(args):
            config_file = args[i + 1]
            i += 2
        elif arg in ['--verbose', '-v']:
            verbose = True
            i += 1
        else:
            remaining.append(arg)
            i += 1
    
    return config_file, verbose, remaining

def main():
    """CLI entry point."""
    try:
        from . import __version__
    except ImportError:
        try:
            import oasist
            __version__ = oasist.__version__
        except ImportError:
            __version__ = "unknown"
    
    raw_args = sys.argv[1:]
    
    # Parse global flags before processing commands
    config_file, verbose, args = parse_args(raw_args)
    
    # Set logging level based on verbose flag
    if verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")
    
    # Handle version and help flags
    if args and args[0] in ['--version', '-V']:
        console.print(f"oasist {__version__}")
        return EXIT_SUCCESS
    
    if not args or args[0] in ['-h', '--help', CMD_HELP]:
        HelpDisplay.show_command(args[1] if len(args) > 1 else '')
        return EXIT_SUCCESS
    
    # Show banner
    console.print(Panel(
        Align.center(Text.assemble(
            "\n", Text("OASist Client Generator", style="accent"),
            "\n", Text("Generate Python clients from OpenAPI schemas", style="dim"), "\n"
        ), vertical="middle"),
        box=box.ROUNDED, padding=(1, 2), title="✨", border_style="accent"
    ))
    console.print(Rule(style="dim"))
    
    # Initialize and load config
    generator = ClientGenerator(output_base=Path(OUTPUT_DIR))
    
    with console.status("[accent]Loading configuration...", spinner="dots"):
        if not ConfigLoader.load(generator, config_file):
            logger.error(f"Failed to load config from {config_file}")
            return EXIT_ERROR
    
    # Handle per-command help
    if '-h' in args or '--help' in args:
        HelpDisplay.show_command(args[0])
        return EXIT_SUCCESS
    
    # Execute command
    if not CommandRegistry.execute(args[0], generator, args):
        console.print(Panel.fit("Invalid command. Use --help for usage.", title="Error", style="error"))
        return EXIT_ERROR
    
    return EXIT_SUCCESS

if __name__ == "__main__":
    sys.exit(main())

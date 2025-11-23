# OASist Client Generator

Generate type-safe Python clients from OpenAPI schemas with a beautiful CLI interface. Supports both JSON and YAML schemas with Orval-inspired configuration, **including advanced API versioning with incremental generation**.

Built on top of **[openapi-python-client](https://github.com/openapi-generators/openapi-python-client)** with enhanced features and developer experience.

## Features

- 🚀 Clean, modular Python package with rich CLI interface
- 📦 Generate type-safe Python clients from OpenAPI specs (JSON/YAML)
- ✨ **Automatic code formatting with Black** (optional, enabled by default)
- 🔄 Schema sanitization and validation with security fixes
- 🎯 Orval-inspired configuration format with environment variable support
- 🏗️ Built with design patterns (Strategy, Command, Dataclass)
- ⚡ Automatic base URL detection and post-hook management
- 🎨 Beautiful terminal UI with progress indicators
- 🔒 Path traversal protection and input validation
- 🔁 Automatic retry logic for common failures
- 🆕 **API Versioning Support** - Generate and manage multiple API versions
- 🆕 **Incremental Generation** - Only generate changed endpoints/models for new versions
- 🆕 **Schema Comparison** - Automatic change detection between API versions
- 🆕 **Version Registry** - Track and manage version metadata

## Installation

```bash
# Install from PyPI
pip install oasist

# Install with Black formatting support (recommended)
pip install oasist[formatting]

# Or install Black separately
pip install black
```

## Quick Start

```bash
# List all configured services
oasist list

# Generate a specific client
oasist generate user_service

# Generate a specific version (for versioned projects)
oasist generate api_service --version 1.2.0

# Generate all clients
oasist generate-all

# List all versions for a service
oasist versions api_service

# Show service details
oasist info user_service

# Force regenerate existing client
oasist generate user_service --force

# Use custom config file
oasist -c production.json generate user_service

# Enable verbose/debug logging
oasist -v generate user_service
```

## Configuration

The generator supports both JSON and YAML OpenAPI documents. It pre-fetches the schema with optional headers/params, then generates via a local temp file to ensure consistent handling of JSON and YAML. Configuration is provided via a single JSON file using an Orval-inspired "projects" structure.

### Configuration File Structure

Create `oasist_config.json` in your project root. The configuration supports two types of projects:

1. **Standard Projects** - Single version API clients
2. **Versioned Projects** - Multiple API versions with incremental generation support

### Complete Configuration Example

```json
{
  "output_dir": "./clients",
  "projects": {
    "api_service": {
      "versioning": {
        "enabled": true,
        "auto_detect": true,
        "base_version": "1.0.0",
        "generation_mode": "changed"
      },
      "versions": {
        "1.0.0": {
          "input": {
            "target": "https://api.example.com/v1/openapi.json",
            "prefer_json": true,
            "headers": {
              "Authorization": "Bearer ${API_TOKEN}"
            }
          },
          "output": {
            "base_url": "https://api.example.com/v1",
            "package_name": "api_service",
            "format_with_black": true
          }
        },
        "1.1.0": {
          "input": {
            "target": "https://api.example.com/v1.1/openapi.json",
            "prefer_json": true
          },
          "output": {
            "base_url": "https://api.example.com/v1.1",
            "package_name": "api_service",
            "format_with_black": true
          }
        },
        "2.0.0": {
          "input": {
            "target": "./schemas/v2.0.0.json",
            "prefer_json": true
          },
          "output": {
            "base_url": "https://api.example.com/v2",
            "package_name": "api_service",
            "format_with_black": true
          }
        }
      }
    },
    "user_service": {
      "input": {
        "target": "https://users.example.com/openapi.json",
        "prefer_json": true
      },
      "output": {
        "dir": "user_service",
        "name": "User Service",
        "base_url": "https://users.example.com",
        "package_name": "user_service",
        "format_with_black": true
      }
    }
  }
}
```

## Configuration Reference

### Global Configuration

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `output_dir` | string | No | `"./clients"` | Base directory where all generated clients will be stored. Can be relative or absolute path. |
| `projects` | object | Yes | - | Object containing all project configurations. Each key is a project identifier. |

### Standard Project Configuration

For projects without versioning, use the standard configuration format:

#### Project Input Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | string | Yes | URL or file path to the OpenAPI schema. Can be HTTP/HTTPS URL or local file path (relative to project root). |
| `prefer_json` | boolean | No | `false` | If `true`, prefers JSON format over YAML when both are available. |
| `params` | object | No | `{}` | Query parameters to include in the schema fetch request. Useful for APIs that require query params. |
| `headers` | object | No | `{}` | Custom HTTP headers for schema fetch requests. Useful for authenticated endpoints. Supports environment variable substitution. |

#### Project Output Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `dir` | string | Yes | Directory name for the generated client. Will be created under `output_dir`. |
| `name` | string | Yes | Human-readable service name. Used in CLI output and documentation. |
| `base_url` | string | No | Service base URL. If not provided, will be auto-detected from `target` URL. |
| `package_name` | string | No | Python package name for the generated client. If not provided, will be auto-generated from service name. |
| `format_with_black` | boolean | No | `true` | Enable automatic code formatting with Black. Set to `false` to disable. |
| `disable_post_hooks` | boolean | No | `true` | Disable post-generation hooks from openapi-python-client. Usually set to `true` for cleaner output. |

### Versioned Project Configuration

For projects with multiple API versions, use the versioning configuration:

#### Versioning Configuration

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `enabled` | boolean | Yes | - | Set to `true` to enable versioning for this project. |
| `auto_detect` | boolean | No | `false` | If `true`, automatically detects version from OpenAPI schema's `info.version` field. |
| `base_version` | string | No | - | The base version string (e.g., `"1.0.0"`). This version will always use full generation. Required if `generation_mode` is `"changed"`. |
| `generation_mode` | string | No | `"full"` | Generation mode: `"full"` (generate complete client) or `"changed"` (incremental - only changed endpoints/models). Base version always uses `"full"` mode. |

#### Version-Specific Configuration

Each version in the `versions` object has its own `input` and `output` configuration:

**Version Input Parameters:**
- Same as standard project `input` parameters (see above)

**Version Output Parameters:**
- Same as standard project `output` parameters, except:
  - `dir` is not used (versions are stored in subdirectories like `1.0.0/`, `1.1.0/`)
  - `name` is not used (uses project name)

### Configuration Examples

#### Example 1: Standard Single-Version Project

```json
{
  "output_dir": "./clients",
  "projects": {
    "blog_api": {
      "input": {
        "target": "https://api.blog.example.com/openapi.json",
        "prefer_json": true
      },
      "output": {
        "dir": "blog_client",
        "name": "Blog API Client",
        "base_url": "https://api.blog.example.com",
        "package_name": "blog_client",
        "format_with_black": true
      }
    }
  }
}
```

**Explanation:**
- `target`: Fetches schema from the provided URL
- `prefer_json`: Prefers JSON format if available
- `dir`: Client will be generated in `./clients/blog_client/`
- `name`: Display name for CLI output
- `base_url`: Base URL for API requests
- `package_name`: Python package name (used in imports)
- `format_with_black`: Automatically formats generated code

#### Example 2: Versioned Project with Full Generation

```json
{
  "output_dir": "./clients",
  "projects": {
    "payment_api": {
      "versioning": {
        "enabled": true,
        "auto_detect": false,
        "base_version": "1.0.0",
        "generation_mode": "full"
      },
      "versions": {
        "1.0.0": {
          "input": {
            "target": "https://api.payment.example.com/v1/openapi.json",
            "prefer_json": true
          },
          "output": {
            "base_url": "https://api.payment.example.com/v1",
            "package_name": "payment_api",
            "format_with_black": true
          }
        },
        "2.0.0": {
          "input": {
            "target": "https://api.payment.example.com/v2/openapi.json",
            "prefer_json": true
          },
          "output": {
            "base_url": "https://api.payment.example.com/v2",
            "package_name": "payment_api",
            "format_with_black": true
          }
        }
      }
    }
  }
}
```

**Explanation:**
- `versioning.enabled`: Enables versioning for this project
- `base_version`: `1.0.0` is the base version
- `generation_mode`: `"full"` means each version generates a complete client
- Each version has its own `input.target` and `output.base_url`
- Generated structure: `./clients/payment_api/1.0.0/` and `./clients/payment_api/2.0.0/`

#### Example 3: Versioned Project with Incremental Generation

```json
{
  "output_dir": "./clients",
  "projects": {
    "shopping_api": {
      "versioning": {
        "enabled": true,
        "auto_detect": true,
        "base_version": "1.0.0",
        "generation_mode": "changed"
      },
      "versions": {
        "1.0.0": {
          "input": {
            "target": "https://api.shop.example.com/v1/openapi.json",
            "prefer_json": true
          },
          "output": {
            "base_url": "https://api.shop.example.com/v1",
            "package_name": "shopping_api",
            "format_with_black": true
          }
        },
        "1.1.0": {
          "input": {
            "target": "https://api.shop.example.com/v1.1/openapi.json",
            "prefer_json": true
          },
          "output": {
            "base_url": "https://api.shop.example.com/v1.1",
            "package_name": "shopping_api",
            "format_with_black": true
          }
        }
      }
    }
  }
}
```

**Explanation:**
- `generation_mode`: `"changed"` enables incremental generation
- `base_version`: `1.0.0` will be fully generated
- `1.1.0`: Will only generate changed/new endpoints and models
- Unchanged code is imported from base version, keeping the structure clean
- `auto_detect`: Automatically detects version from schema's `info.version`

#### Example 4: Using Local Schema Files

```json
{
  "output_dir": "./clients",
  "projects": {
    "internal_api": {
      "versioning": {
        "enabled": true,
        "base_version": "1.0.0",
        "generation_mode": "changed"
      },
      "versions": {
        "1.0.0": {
          "input": {
            "target": "./schemas/v1.0.0.json",
            "prefer_json": true
          },
          "output": {
            "base_url": "https://internal.example.com/api/v1",
            "package_name": "internal_api",
            "format_with_black": true
          }
        },
        "1.2.0": {
          "input": {
            "target": "./schemas/v1.2.0.yaml",
            "prefer_json": false
          },
          "output": {
            "base_url": "https://internal.example.com/api/v1.2",
            "package_name": "internal_api",
            "format_with_black": true
          }
        }
      }
    }
  }
}
```

**Explanation:**
- `target` can be a local file path (relative to project root)
- Supports both `.json` and `.yaml` files
- `prefer_json` should match the file format for better performance

### Environment Variable Substitution

OASist supports environment variable substitution in configuration files using the `${VAR}` or `${VAR:default}` syntax:

- `${VAR}` - Replace with environment variable value (warns if not found)
- `${VAR:default}` - Replace with environment variable value or use default if not found

**Example:**
```json
{
  "projects": {
    "api": {
      "input": {
        "target": "${API_SCHEMA_URL:http://localhost:8000/openapi.json}",
        "headers": {
          "Authorization": "Bearer ${API_TOKEN}"
        }
      },
      "output": {
        "base_url": "${API_BASE_URL:http://localhost:8000}"
      }
    }
  }
}
```

Create a `.env` file in your project root:
```
API_SCHEMA_URL=https://api.production.com/openapi.json
API_BASE_URL=https://api.production.com
API_TOKEN=your_secret_token_here
```

### Custom Headers

You can specify custom headers for schema fetch requests, which is useful for authenticated endpoints:

```json
{
  "projects": {
    "protected_api": {
      "input": {
        "target": "https://api.example.com/openapi.json",
        "headers": {
          "Authorization": "Bearer ${API_TOKEN}",
          "X-Custom-Header": "custom-value",
          "X-API-Key": "${API_KEY:default_key}"
        }
      },
      "output": {
        "dir": "protected_api_client"
      }
    }
  }
}
```

## Usage in Code

### Standard (Non-Versioned) Clients

```python
# Import the generated client
from clients.user_service.user_service_client import Client

# Initialize client with base URL
client = Client(base_url="https://api.example.com")

# Use the client to call endpoints
# List all users
users_response = client.users.list_users()

# Get a specific user
user = client.users.get_user(user_id=123)

# Create a new user
new_user = client.users.create_user(
    body={
        "name": "John Doe",
        "email": "john@example.com"
    }
)

# Access models
from clients.user_service.user_service_client.models import User, UserCreate

user_model = User(
    id=1,
    name="John Doe",
    email="john@example.com"
)
```

### Versioned Clients

For versioned projects, use the version selector:

```python
# Import the version selector
from clients.api_service import get_client

# Get client for a specific version (defaults to latest)
client_v1 = get_client("1.0.0", base_url="https://api.example.com/v1", token="your-token")
client_v2 = get_client("2.0.0", base_url="https://api.example.com/v2", token="your-token")

# Or use default (latest version)
client = get_client(base_url="https://api.example.com/v2", token="your-token")

# Use the client - same API as standard clients
users = client.users.list_users()
user = client.users.get_user(user_id=123)

# Access version-specific models
from clients.api_service.v2_0_0.models import User, Order
from clients.api_service.v1_0_0.models import User as UserV1

# Models from base version are available in newer versions via imports
# (when using incremental generation)
```

### Complete Usage Example

```python
from clients.shopping_api import get_client

# Initialize client for version 1.1.0
client = get_client(
    version="1.1.0",
    base_url="https://api.shop.example.com/v1.1",
    token="your-auth-token"
)

# Call endpoints
try:
    # List products
    products = client.products.list_products()
    print(f"Found {len(products)} products")
    
    # Get a specific product
    product = client.products.get_product(product_id=123)
    print(f"Product: {product.name} - ${product.price}")
    
    # Create an order
    order = client.orders.create_order(
        body={
            "product_id": 123,
            "quantity": 2,
            "shipping_address": {
                "street": "123 Main St",
                "city": "New York",
                "zip": "10001"
            }
        }
    )
    print(f"Order created: {order.id}")
    
    # Access models directly
    from clients.shopping_api.v1_1_0.models import Product, Order, ShippingAddress
    
    new_product = Product(
        name="New Product",
        price=99.99,
        description="A great product"
    )
    
except Exception as e:
    print(f"Error: {e}")
```

### Working with Models

```python
from clients.api_service.v2_0_0.models import User, UserCreate, UserUpdate

# Create model instances
user_create = UserCreate(
    name="Jane Doe",
    email="jane@example.com",
    age=30
)

# Models are Pydantic models, so they have validation
try:
    invalid_user = UserCreate(
        name="Test",
        email="invalid-email",  # Will raise validation error
        age=-5  # Invalid age
    )
except Exception as e:
    print(f"Validation error: {e}")

# Convert to dict
user_dict = user_create.dict()

# Convert from dict
user = User(**user_dict)

# Access model fields
print(user.name)
print(user.email)
```

## All Commands

### Global Options

```bash
# Use custom configuration file
oasist -c custom_config.json <command>
oasist --config custom_config.json <command>

# Enable verbose/debug logging
oasist -v <command>
oasist --verbose <command>

# Combine options
oasist -v -c prod.json generate-all
```

### Basic Commands

```bash
# Show general help
oasist --help
oasist help

# Show command-specific help
oasist help generate
oasist generate --help

# Show version information
oasist --version

# List all services and their generation status
oasist list

# Show detailed information about a service
oasist info <service_name>

# List all versions for a versioned service
oasist versions <service_name>
```

### Generation Commands

```bash
# Generate client for a specific service
oasist generate <service_name>

# Generate a specific version (for versioned projects)
oasist generate <service_name> --version 1.2.0

# Force regenerate (overwrite existing)
oasist generate <service_name> --force

# Force regenerate a specific version
oasist generate <service_name> --version 1.2.0 --force

# Generate clients for all configured services
oasist generate-all

# Generate all with force overwrite
oasist generate-all --force
```

## Versioning Features

### Generation Modes

#### Full Generation Mode (`generation_mode: "full"`)

Each version generates a complete, independent client:

```
clients/api_service/
├── __init__.py              # Version selector
├── version_registry.json    # Version metadata
├── 1.0.0/                   # Complete client for v1.0.0
│   ├── api/
│   ├── models/
│   └── client.py
└── 2.0.0/                   # Complete client for v2.0.0
    ├── api/
    ├── models/
    └── client.py
```

**Use when:**
- Versions have significant differences
- You want completely independent clients
- Simpler structure is preferred

#### Incremental Generation Mode (`generation_mode: "changed"`)

Only changed endpoints and models are generated. Unchanged code is imported from the base version:

```
clients/api_service/
├── __init__.py              # Version selector
├── version_registry.json    # Version metadata + change tracking
├── 1.0.0/                   # Base version (full generation)
│   ├── api/
│   │   ├── users/
│   │   ├── products/
│   │   └── orders/
│   └── models/
│       ├── User.py
│       ├── Product.py
│       └── Order.py
└── 1.1.0/                   # Incremental version (only changes)
    ├── api/
    │   └── reviews/         # New endpoint module
    │       └── create_review.py
    └── models/
        └── Review.py        # New model
```

**Use when:**
- Versions have mostly unchanged APIs
- You want to minimize code duplication
- You want to see what changed between versions

### Version Registry

Each versioned project has a `version_registry.json` file that tracks:

- Generated versions and timestamps
- OpenAPI version information
- Endpoint signatures for each version
- Change detection results (for incremental generation)
- Base version references

**Example registry:**
```json
{
  "versions": {
    "1.0.0": {
      "generated_at": "2024-01-15T10:30:00Z",
      "openapi_version": "3.1.0",
      "schema_url": "https://api.example.com/v1/openapi.json",
      "endpoints": ["GET /users", "POST /users", "GET /users/{id}"],
      "endpoint_count": 15
    },
    "1.1.0": {
      "generated_at": "2024-01-20T14:45:00Z",
      "openapi_version": "3.1.0",
      "schema_url": "https://api.example.com/v1.1/openapi.json",
      "endpoints": ["GET /users", "POST /users", "GET /users/{id}", "GET /reviews"],
      "endpoint_count": 16,
      "changed_endpoints": ["GET /reviews"],
      "changed_models": ["Review"],
      "base_version": "1.0.0"
    }
  },
  "metadata": {
    "base_version": "1.0.0",
    "latest_version": "1.1.0"
  }
}
```

### Auto-Detection

When `auto_detect: true`, OASist automatically:

1. Fetches the schema from the `target` URL
2. Extracts the version from `info.version` field
3. Uses that version for directory naming and imports
4. Updates the registry with detected version

**Example:**
```json
{
  "versioning": {
    "enabled": true,
    "auto_detect": true,
    "base_version": "1.0.0"
  },
  "versions": {
    "1.0.0": {
      "input": {
        "target": "https://api.example.com/openapi.json"
      }
    }
  }
}
```

If the schema has `"info": {"version": "1.2.3"}`, it will be generated as version `1.2.3`.

## Project Structure

### Standard Project Structure

```
clients/
└── user_service/              # Generated client
    ├── pyproject.toml
    └── user_service_client/
        ├── __init__.py
        ├── client.py          # Main client class
        ├── api/               # API endpoints
        │   ├── users/
        │   │   ├── __init__.py
        │   │   ├── list_users.py
        │   │   └── get_user.py
        │   └── orders/
        ├── models/            # Data models
        │   ├── __init__.py
        │   ├── user.py
        │   └── order.py
        └── types.py           # Type definitions
```

### Versioned Project Structure (Full Mode)

```
clients/
└── api_service/
    ├── __init__.py            # Version selector: get_client()
    ├── version_registry.json  # Version metadata
    ├── 1.0.0/                 # Version 1.0.0 client
    │   ├── api/
    │   ├── models/
    │   └── client.py
    ├── 1.1.0/                 # Version 1.1.0 client
    │   ├── api/
    │   ├── models/
    │   └── client.py
    └── 2.0.0/                 # Version 2.0.0 client
        ├── api/
        ├── models/
        └── client.py
```

### Versioned Project Structure (Incremental Mode)

```
clients/
└── api_service/
    ├── __init__.py            # Version selector
    ├── version_registry.json  # Version metadata + changes
    ├── .schema_cache/         # Cached schemas for comparison
    │   └── 1.0.0.json
    ├── 1.0.0/                 # Base version (full)
    │   ├── api/
    │   │   ├── users/
    │   │   └── products/
    │   └── models/
    │       ├── User.py
    │       └── Product.py
    └── 1.1.0/                 # Incremental version (only changes)
        ├── api/
        │   └── reviews/       # Only new/changed endpoints
        │       └── create_review.py
        └── models/
            └── Review.py      # Only new/changed models
```

## Requirements

### Core Dependencies
- Python 3.8+
- openapi-python-client >= 0.26.1
- requests >= 2.31.0
- pyyaml >= 6.0.1
- rich >= 13.7.0
- python-dotenv >= 1.0.1

### Optional Dependencies
- black >= 23.0.0 (for automatic code formatting)

Install with formatting support:
```bash
pip install oasist[formatting]
```

## Troubleshooting

### Schema URL not accessible
Ensure the service is running and the schema endpoint is correct:
```bash
curl https://api.example.com/openapi.json
```

### Permission errors
Ensure write permissions for the clients directory:
```bash
chmod -R u+w clients/
```

### Client generation fails
Check if openapi-python-client is installed:
```bash
pip install --upgrade openapi-python-client
```

Enable debug logging:
```bash
oasist -v generate <service_name>
```

### Black formatting not working
Check if Black is installed:
```bash
black --version
```

Install Black if needed:
```bash
pip install black
# Or
pip install oasist[formatting]
```

Disable formatting if not needed:
```json
{
  "output": {
    "format_with_black": false
  }
}
```

### Version not found error
If you get "Version X not found" when using `get_client()`:

1. Check that the version was generated:
   ```bash
   oasist versions <service_name>
   ```

2. Regenerate the version:
   ```bash
   oasist generate <service_name> --version <version> --force
   ```

3. Check the `version_registry.json` file to see registered versions

### Incremental generation issues

**Base version schema not found:**
- Ensure base version is generated first
- Check that schema cache exists in `.schema_cache/` directory
- Regenerate base version if needed

**Import errors in incremental clients:**
- Ensure base version directory exists
- Check that import paths are correct (they use normalized version names)
- Regenerate both base and incremental versions

## Design Patterns Used

OASist uses several design patterns to ensure maintainability and extensibility:

- **Strategy Pattern**: `SchemaParser` protocol for pluggable JSON/YAML parsing
- **Command Pattern**: CLI commands encapsulate different operations (list, generate, info, versions)
- **Dataclass Pattern**: Type-safe `ServiceConfig` with validation
- **Context Manager**: Temporary file management with automatic cleanup
- **Template Method**: Generator execution with customizable hooks
- **Registry Pattern**: Version metadata tracking and management

### Why the Patterns?

While this adds some code complexity, the benefits are:

✅ **Easy to extend** - Add new parsers, commands, or validators without touching existing code  
✅ **Type-safe** - Dataclasses provide validation and IDE autocomplete  
✅ **Testable** - Each component can be tested independently  
✅ **Maintainable** - Clear separation of concerns makes debugging easier  

For **simple use cases**, you only interact with the CLI - the patterns are invisible. For **advanced use cases**, the modular design allows programmatic usage and customization.

## Advanced Usage

### Programmatic Usage

```python
from oasist import ClientGenerator, ServiceConfig, VersioningConfig, VersionConfig
from pathlib import Path

# Create generator with custom output directory
generator = ClientGenerator(output_base=Path("./my_clients"))

# Add standard service
generator.add_service("api", ServiceConfig(
    name="API Service",
    schema_url="https://api.example.com/openapi.json",
    output_dir="api_client",
    format_with_black=True
))

# Add versioned service
versioning = VersioningConfig(
    enabled=True,
    auto_detect=True,
    base_version="1.0.0",
    generation_mode="changed"
)

versions = {
    "1.0.0": VersionConfig(
        version="1.0.0",
        input={"target": "https://api.example.com/v1/openapi.json"},
        output={"base_url": "https://api.example.com/v1", "package_name": "api"}
    ),
    "1.1.0": VersionConfig(
        version="1.1.0",
        input={"target": "https://api.example.com/v1.1/openapi.json"},
        output={"base_url": "https://api.example.com/v1.1", "package_name": "api"}
    )
}

generator.add_service("versioned_api", ServiceConfig(
    name="Versioned API",
    schema_url="https://api.example.com/v1/openapi.json",
    output_dir="versioned_api",
    versioning=versioning,
    versions=versions
))

# Generate
generator.generate("api", force=True)

# Generate specific version
generator.generate("versioned_api", force=True, version="1.1.0")

# Generate all
generator.generate_all(force=True)
```

## Examples

### Example 1: Generate Standard Client

```bash
$ oasist generate user_service
INFO: ✓ Generated client: user_service → clients/user_service
```

### Example 2: Generate Versioned Client

```bash
$ oasist generate api_service
INFO: Generated version '1.0.0' → clients/api_service/1.0.0
INFO: Using incremental generation for version '1.1.0' (base: '1.0.0')
INFO: Change detection for version '1.1.0':
INFO:   Endpoints - New: 2, Modified: 1, Unchanged: 12, Removed: 0
INFO:   Models - New: 3, Modified: 2, Unchanged: 15
INFO: Generated incremental version '1.1.0' → clients/api_service/1.1.0
✨ Generated api_service (2 version(s)) → clients/api_service
```

### Example 3: List All Services

```bash
$ oasist list

                              Configured Services                               
╭────────┬──────────────┬──────────────┬─────────────┬─────────────────────────╮
│ Status │ Key          │ Name         │ Schema URL  │ Versions                │
├────────┼──────────────┼──────────────┼─────────────┼─────────────────────────┤
│ ✓      │ api_service  │ API Service  │ https://... │ 3 version(s), latest:   │
│        │              │              │             │ 2.0.0                    │
│ ○      │ user_service │ User Service │ https://... │                         │
╰────────┴──────────────┴──────────────┴─────────────┴─────────────────────────╯
```

### Example 4: List Versions

```bash
$ oasist versions api_service

                   Versions for api_service                   
╭─────────┬────────┬──────────────────┬───────────┬─────────╮
│ Version │ Status │ Generated        │ Endpoints │ OpenAPI │
├─────────┼────────┼──────────────────┼───────────┼─────────┤
│ 1.0.0   │ ✓      │ 2024-01-15 10:30 │        15 │ 3.1.0   │
│ 1.1.0   │ ✓      │ 2024-01-20 14:45 │        16 │ 3.1.0   │
│ 2.0.0   │ ✓      │ 2024-01-25 09:15 │        20 │ 3.1.0   │
╰─────────┴────────┴──────────────────┴───────────┴─────────╯
```

## Contributing

Contributions are welcome! To extend or modify:

1. Fork the repository
2. Create a feature branch
3. Make your changes with appropriate tests
4. Submit a pull request

### Development Setup

```bash
# Clone the repository
git clone https://github.com/AhEsmaeili79/oasist.git
cd oasist

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install in development mode
pip install -e .

# Run tests
pytest

# Run with verbose output
pytest -v

# Run only versioning tests
pytest tests/test_versioning.py -v
```

## License

MIT License - See [LICENSE](LICENSE) file for details

Copyright (c) 2024 AH Esmaeili

## Support

For issues or questions:
- Check the Troubleshooting section
- Review the OpenAPI schema URL accessibility
- Verify all dependencies are installed
- Enable debug logging for detailed error information
- Check the version registry for version-related issues

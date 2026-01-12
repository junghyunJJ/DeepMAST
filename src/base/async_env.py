"""Async environment variable loading to prevent blocking I/O in ASGI contexts"""

import os
from pathlib import Path
from functools import lru_cache
import aiofiles


# Cache to store loaded environment state
_env_loaded = False


async def load_env_async(override: bool = True) -> None:
    """Load environment variables asynchronously from .env file

    This function prevents blocking I/O warnings in ASGI contexts (like LangGraph dev server)
    by using async file operations instead of synchronous reads.

    Args:
        override: If True, override existing environment variables.
                  If False, only set variables that don't already exist.
    """
    global _env_loaded

    # Skip if already loaded and not overriding
    if _env_loaded and not override:
        return

    # Find the project root (.env should be at project root)
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / '.env'

    # Return early if .env doesn't exist
    if not env_path.exists():
        return

    try:
        async with aiofiles.open(env_path, encoding='utf-8') as f:
            async for line in f:
                stripped_line = line.strip()

                # Skip comments and empty lines
                if not stripped_line or stripped_line.startswith('#'):
                    continue

                # Parse key=value pairs
                if '=' in stripped_line:
                    # Split on first = only (value might contain =)
                    key, value = stripped_line.split('=', 1)
                    key = key.strip()
                    value = value.strip()

                    # Remove surrounding quotes if present
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]

                    # Handle special escape sequences
                    value = value.replace('\\n', '\n').replace('\\t', '\t')

                    # Only set if override=True or key doesn't exist
                    if override or key not in os.environ:
                        os.environ[key] = value

        _env_loaded = True

    except Exception as e:
        # Log error but don't fail - environment may have been loaded elsewhere
        import warnings
        warnings.warn(f"Failed to load .env file asynchronously: {e}", stacklevel=2)


def load_env_sync_fallback(override: bool = True) -> None:
    """Synchronous fallback for non-async contexts

    Only use this in:
    - CLI scripts (like chatbot.py entry point)
    - Test files
    - Example scripts
    - One-time setup scripts

    DO NOT use in:
    - Agent modules
    - ASGI handlers
    - Graph builders (when running in LangGraph dev)
    - Any code that runs within an event loop

    Args:
        override: If True, override existing environment variables
    """
    from dotenv import load_dotenv

    # Use the same project root logic
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / '.env'

    if env_path.exists():
        load_dotenv(env_path, override=override)
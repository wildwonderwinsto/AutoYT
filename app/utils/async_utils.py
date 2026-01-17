"""Utilities for handling async operations in Celery tasks."""

import asyncio
import sys


def run_async(coro):
    """
    Run an async coroutine in a Celery task, handling Windows event loop issues.
    
    This function handles the common issue where asyncio.run() creates a new event loop
    that conflicts with SQLAlchemy async connections on Windows/Celery.
    
    Args:
        coro: The coroutine to run
        
    Returns:
        The result of the coroutine
    """
    # Try to use nest_asyncio if available (fixes Windows/Celery issues)
    try:
        import nest_asyncio
        nest_asyncio.apply()
        return asyncio.run(coro)
    except ImportError:
        # nest_asyncio not installed, try alternative approach
        pass
    
    # Try standard asyncio.run first
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        if "attached to a different loop" in str(e) or "Event loop is closed" in str(e):
            # Windows/Celery event loop conflict - try to get existing loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                return loop.run_until_complete(coro)
            except Exception:
                # Last resort: try nest_asyncio again (might have been installed)
                try:
                    import nest_asyncio
                    nest_asyncio.apply()
                    return asyncio.run(coro)
                except ImportError:
                    # If all else fails, raise the original error
                    raise RuntimeError(
                        "Event loop conflict detected. Please install nest-asyncio: "
                        "pip install nest-asyncio"
                    ) from e
        raise

"""Entry point for ``python3 -m a2a_orchestrator``.

Delegates to :func:`a2a_orchestrator.server.main` which starts the
FastMCP server on stdio.
"""
from a2a_orchestrator.server import main

if __name__ == "__main__":
    main()

"""`python -m pisama_n8n_server.mcp` — stdio entry point."""
import asyncio

from .server import main

asyncio.run(main())

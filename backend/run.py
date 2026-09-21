"""Dev server entrypoint.

uvicorn's asyncio loop factory hardcodes ProactorEventLoop on Windows, which
psycopg async (the LangGraph checkpointer) can't run on. loop="none" defers
loop creation to the event-loop policy, which we force to Selector here.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        loop="none",
    )

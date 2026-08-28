"""Local backend runner with reliable Windows process replacement."""

import uvicorn


def run() -> None:
    uvicorn.run("app.main:app", host="localhost", port=8000)

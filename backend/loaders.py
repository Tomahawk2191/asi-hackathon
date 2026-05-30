"""Helpers for reading JSON files and parsing them into typed models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, TypeVar, Union

from pydantic import BaseModel

from flights import RoutesSnapshot

T = TypeVar("T", bound=BaseModel)

PathLike = Union[str, Path]


def load_json_model(path: PathLike, parser: Callable[[dict], T]) -> T:
    """Read ``path`` as JSON and parse it into a typed model.

    ``parser`` maps the decoded JSON (a dict) to a Pydantic model instance,
    e.g. ``StatesResponse.from_raw``. The return type is inferred from the
    parser, so callers get full static type checking on the result.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        json.JSONDecodeError: if the file is not valid JSON.
        pydantic.ValidationError: if the data does not match the model.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    payload = json.loads(path.read_text())
    return parser(payload)


def load_routes(path: PathLike) -> RoutesSnapshot:
    """Read a routes/flights JSON file into a typed RoutesSnapshot."""
    return load_json_model(path, RoutesSnapshot.from_raw)

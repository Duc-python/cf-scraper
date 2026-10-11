"""Request schema - mirrors src/module/reqValidate.js.

Same fields, same required set, same closed object (extra="forbid" is
additionalProperties: false).
"""
from __future__ import annotations

from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, StrictInt, field_validator


class ProxyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: StrictInt
    username: Optional[str] = None
    password: Optional[str] = None


class ScrapeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["source", "turnstile-min", "turnstile-max", "waf-session"]
    url: str
    proxy: Optional[ProxyConfig] = None
    authToken: Optional[str] = None
    siteKey: Optional[str] = None

    @field_validator("url")
    @classmethod
    def _must_be_uri(cls, value: str) -> str:
        parts = urlparse(value)
        if not parts.scheme or not parts.netloc:
            raise ValueError("must be a valid uri")
        return value

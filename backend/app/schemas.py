"""DesignSpec v1 + Brief contracts. Commercial text always comes from Brief, never from the model."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class Brief(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_name: str = Field(min_length=1, max_length=60)
    headline: str = Field(default="", max_length=80)  # empty -> AI suggestion (labelled)
    price: str = Field(default="", max_length=40)  # optional, user-confirmed
    cta: str = Field(min_length=1, max_length=40)
    history_event_id: str | None = Field(default=None, max_length=80)


class BBox(BaseModel):
    """Normalised [0..1] box, origin top-left."""

    model_config = ConfigDict(extra="forbid")
    x: float
    y: float
    w: float
    h: float


class Anchors(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: BBox
    product: BBox
    price: BBox
    cta: BBox


Treatment = Literal["card", "plain", "badge"]


class Variant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Literal["A", "B", "C"]
    style: Literal["faithful", "minimal", "promotion"]
    bg: str
    fg: str
    accent: str
    headline_scale: float = Field(ge=0.6, le=1.4)
    product_scale: float = Field(ge=0.6, le=1.0)
    treatment: Treatment

    @field_validator("bg", "fg", "accent")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX.match(v):
            raise ValueError("color must be #RRGGBB")
        return v.upper()


class AIDesign(BaseModel):
    """What the model returns. Validated, then repaired by validator.py."""

    model_config = ConfigDict(extra="ignore")
    needs_clarification: bool
    layout_reading: str = Field(default="", max_length=400)
    headline_suggestion: str = Field(default="", max_length=80)
    anchors: Anchors
    variants: list[Variant] = Field(min_length=1, max_length=3)


class DesignSpec(BaseModel):
    schema_version: str = "1.0"
    canvas: dict = {"width": 1080, "height": 1080}
    needs_clarification: bool
    layout_source: Literal["sketch", "suggested"]  # "suggested" must be shown to the user
    layout_reading: str
    headline_source: Literal["user", "ai_suggestion", "product_name"]
    anchors: Anchors
    variants: list[Variant]
    repairs: list[str] = []

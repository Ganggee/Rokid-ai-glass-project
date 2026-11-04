"""Pydantic request/response models (OpenAPI is served at /docs)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorBody


# ------------------------------------------------------------------ inventory
class Product(BaseModel):
    product_id: str
    product_name: str
    category: Optional[str] = None
    stock_qty: int
    unit: str = "ea"
    barcode: Optional[str] = None
    qr_value: Optional[str] = None
    lot_no: Optional[str] = None
    expiration_date: Optional[str] = None
    location: Optional[str] = None
    is_demo: bool = False
    updated_at: str


class ProductList(BaseModel):
    items: list[Product]
    count: int


class Transaction(BaseModel):
    id: int
    product_id: str
    tx_type: str
    quantity_delta: int
    stock_before: int
    stock_after: int
    idempotency_key: Optional[str] = None
    source: str
    client_timestamp: Optional[str] = None
    note: Optional[str] = None
    created_at: str


class TransactionList(BaseModel):
    items: list[Transaction]
    count: int


class UseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(default=1, ge=1, le=1000)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:\-]+$")
    confirmed: bool = Field(description="Must be true. The client sends true only after the user confirmed on the HUD.")
    client_timestamp: Optional[str] = Field(default=None, max_length=64)
    source: str = Field(default="api", max_length=32)
    note: Optional[str] = Field(default=None, max_length=200)


class UseResponse(BaseModel):
    product: Product
    transaction: Transaction
    replayed: bool = Field(description="true when the same idempotency_key was already applied; no second decrement happened")


class OperationStatus(BaseModel):
    idempotency_key: str
    applied: bool
    transaction: Optional[Transaction] = None
    product: Optional[Product] = None


class ResolveCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=512)
    code_type: Literal["auto", "qr", "barcode"] = "auto"


class ResolveResult(BaseModel):
    status: Literal["matched", "candidates", "unrecognized"]
    product: Optional[Product] = None
    candidates: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    message: str = ""


class ParseCommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=300)


class ParsedCommand(BaseModel):
    intent: Literal["query_stock", "use", "confirm", "cancel", "unknown"]
    quantity: Optional[int] = None
    product: Optional[Product] = None
    candidates: list[dict[str, Any]] = []
    requires_confirmation: bool
    text: str
    note: str = "Parsed command only. No stock was changed; the client must show a confirmation and call /use."


class ImportPreview(BaseModel):
    batch_id: str
    filename: str
    file_sha256: str
    row_count: int
    valid_rows: int
    error_count: int
    warning_count: int
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    column_mapping: dict[str, str]


class ImportCommitRequest(BaseModel):
    batch_id: str
    mode: Literal["seed", "adjust", "metadata"] = Field(
        description="seed: create new products only, never touch existing stock. "
        "adjust: create new products and set existing stock to the file value (recorded as an 'adjust' transaction). "
        "metadata: update names/codes/lot/location only; stock untouched."
    )
    skip_invalid_rows: bool = False


# ------------------------------------------------------------------ meals
class Region(BaseModel):
    """bbox: x,y,w,h ; polygon: points=[[x,y],...] — pixel coordinates of the original photo."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["bbox", "polygon"]
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    points: Optional[list[list[float]]] = None

    @field_validator("points")
    @classmethod
    def _points(cls, value):
        if value is not None:
            if len(value) < 3 or any(len(p) != 2 for p in value):
                raise ValueError("polygon needs >= 3 [x, y] points")
        return value


class MealItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    nutrition_ref_id: Optional[str] = None
    initial_serving_grams: Optional[float] = Field(default=None, gt=0, le=5000)
    serving_source: Optional[Literal["user", "demo_assumption"]] = None
    before_region: Optional[Region] = None
    after_region: Optional[Region] = None


class MealItemsRequest(BaseModel):
    items: list[MealItemIn] = Field(min_length=1, max_length=20)


class AnalyzeRequest(BaseModel):
    method: Literal["auto", "manual", "model"] = "auto"


class NutritionRef(BaseModel):
    id: str
    food_name: str
    aliases: list[str] = []
    kcal_per_100g: Optional[float] = None
    carbs_g_per_100g: Optional[float] = None
    protein_g_per_100g: Optional[float] = None
    fat_g_per_100g: Optional[float] = None
    source: str
    source_detail: Optional[str] = None
    is_demo: bool

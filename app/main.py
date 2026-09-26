"""单位换算 API。

POST /convert 接收 {"value": "...", "from": "...", "to": "..."}，
返回 {"result": "..."}；错误一律返回 422。
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .converter import (
    DimensionMismatchError,
    InvalidValueError,
    OffsetScaleInCompoundError,
    Quantity,
    UnitSyntaxError,
    convert_value,
    format_result,
    parse_expression,
    parse_value,
)

app = FastAPI(
    title="Unit Converter API",
    version="1.0.0",
    description="长度 / 质量 / 时间 / 温度四维量纲的单位换算，"
                "支持复合单位表达式与 °C / °F 偏移温标。",
)


class ConvertRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    value: str = Field(max_length=10_000, description="有限十进制字符串")
    from_: str = Field(alias="from", max_length=2_000, description="源单位表达式")
    to: str = Field(max_length=2_000, description="目标单位表达式")


class ConvertResponse(BaseModel):
    result: str


def _unprocessable(error: str, message: str, **extra) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"error": error, "message": message, **extra},
    )


def _parse_unit_field(expr: str, field: str) -> Quantity:
    try:
        return parse_expression(expr)
    except UnitSyntaxError as exc:
        raise _unprocessable(
            "syntax_error", exc.message, field=field, position=exc.position)
    except OffsetScaleInCompoundError as exc:
        raise _unprocessable(
            "offset_temperature_in_compound", str(exc),
            field=field, position=exc.position)


@app.post("/convert", response_model=ConvertResponse)
def convert_endpoint(req: ConvertRequest) -> ConvertResponse:
    try:
        value = parse_value(req.value)
    except InvalidValueError as exc:
        raise _unprocessable("invalid_value", str(exc))

    source = _parse_unit_field(req.from_, "from")
    target = _parse_unit_field(req.to, "to")

    try:
        result = convert_value(value, source, target)
    except DimensionMismatchError as exc:
        raise _unprocessable("dimension_mismatch", str(exc))

    return ConvertResponse(result=format_result(result))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

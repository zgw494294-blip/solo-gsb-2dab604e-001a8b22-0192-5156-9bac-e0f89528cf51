"""单位换算 API。

POST /convert 接收 {"value": "...", "from": "...", "to": "..."}，
返回 {"result": "..."}；错误一律返回 422。

POST /infer-dimensions 接收多条乘积等式 {"equations": [...]}，推断未知
变量的（长度、质量、时间、温度）四维量纲；矛盾、欠定或分数解返回 422。
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
from .dimensions import (
    DimensionInferenceError,
    EquationInput,
    FactorInput,
    UnitFactorError,
    infer_dimensions,
)

app = FastAPI(
    title="Unit Converter API",
    version="1.1.0",
    description="长度 / 质量 / 时间 / 温度四维量纲的单位换算，"
                "支持复合单位表达式、°C / °F 偏移温标与量纲推断。",
)


class ConvertRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    value: str = Field(max_length=10_000, description="有限十进制字符串")
    from_: str = Field(alias="from", max_length=2_000, description="源单位表达式")
    to: str = Field(max_length=2_000, description="目标单位表达式")


class ConvertResponse(BaseModel):
    result: str


class FactorModel(BaseModel):
    """乘积等式中的一个因子：var 与 unit 恰有一个，power ∈ [-6, 6]，默认 1。"""
    model_config = ConfigDict(extra="forbid")

    var: str | None = Field(default=None, min_length=1, max_length=64)
    unit: str | None = Field(default=None, min_length=1, max_length=2_000)
    power: int = Field(default=1, ge=-6, le=6)

    @model_validator(mode="after")
    def _exactly_one_of_var_or_unit(self) -> "FactorModel":
        if (self.var is None) == (self.unit is None):
            raise ValueError('exactly one of "var" or "unit" is required')
        if self.var is not None and not self.var.strip():
            raise ValueError('"var" must not be blank')
        return self


class EquationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left: list[FactorModel] = Field(min_length=1, max_length=50)
    right: list[FactorModel] = Field(min_length=1, max_length=50)


class InferDimensionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equations: list[EquationModel] = Field(min_length=1, max_length=100)


class DimensionVector(BaseModel):
    length: int
    mass: int
    time: int
    temperature: int


class InferDimensionsResponse(BaseModel):
    dimensions: dict[str, DimensionVector]


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


@app.post("/infer-dimensions", response_model=InferDimensionsResponse)
def infer_dimensions_endpoint(
        req: InferDimensionsRequest) -> InferDimensionsResponse:
    equations = [
        EquationInput(
            left=tuple(FactorInput(var=f.var, unit=f.unit, power=f.power)
                       for f in eq.left),
            right=tuple(FactorInput(var=f.var, unit=f.unit, power=f.power)
                        for f in eq.right),
        )
        for eq in req.equations
    ]

    try:
        dimensions = infer_dimensions(equations)
    except UnitFactorError as exc:
        extra = {"equation": exc.equation, "side": exc.side,
                 "factor": exc.factor}
        if exc.position is not None:
            extra["position"] = exc.position
        raise _unprocessable(exc.kind, exc.message, **extra)
    except DimensionInferenceError as exc:
        raise _unprocessable(exc.error, exc.message, **exc.extra)

    ordered = {
        name: DimensionVector(
            length=vec[0], mass=vec[1], time=vec[2], temperature=vec[3])
        for name, vec in sorted(dimensions.items())
    }
    return InferDimensionsResponse(dimensions=ordered)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

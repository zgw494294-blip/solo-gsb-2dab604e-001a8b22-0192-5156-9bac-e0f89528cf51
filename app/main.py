"""单位换算 API。

- POST /convert：接收 {"value": "...", "from": "...", "to": "..."}，
  返回 {"result": "..."}；错误一律返回 422。
- POST /infer-dimensions：依据多条乘积等式推断未知变量的四维量纲。
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
from .inference import InferenceError, ProductEquation, infer_dimensions

app = FastAPI(
    title="Unit Converter API",
    version="1.0.0",
    description="长度 / 质量 / 时间 / 温度四维量纲的单位换算，"
                "支持复合单位表达式与 °C / °F 偏移温标，"
                "并支持由乘积等式推断未知变量量纲。",
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


# ---------------------------------------------------------------------------
# POST /infer-dimensions：由乘积等式推断四维量纲
# ---------------------------------------------------------------------------

class FactorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    var: str | None = Field(default=None, min_length=1, max_length=100)
    unit: str | None = Field(default=None, min_length=1, max_length=2_000)
    power: int = Field(default=1, ge=-6, le=6, description="整数幂，默认 1")

    @model_validator(mode="after")
    def _exactly_one_kind(self) -> "FactorModel":
        # 纯空白名没有意义，按缺失处理。
        if self.var is not None and not self.var.strip():
            raise ValueError("var must not be blank")
        if (self.var is None) == (self.unit is None):
            raise ValueError("each factor must have exactly one of 'var' or 'unit'")
        return self


class EquationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left: list[FactorModel] = Field(min_length=1, max_length=64)
    right: list[FactorModel] = Field(min_length=1, max_length=64)


class InferDimensionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equations: list[EquationModel] = Field(min_length=1, max_length=64)


class DimensionModel(BaseModel):
    length: int
    mass: int
    time: int
    temperature: int


class InferDimensionsResponse(BaseModel):
    dimensions: dict[str, DimensionModel]


def _factor_dims(
    factor: FactorModel, equation: int, side: str, index: int
) -> tuple[str | None, tuple[int, int, int, int]]:
    """返回 (变量名, 量纲)；unit 因子用现有解析器只取量纲，拒绝 °C / °F。"""
    location = {"equation": equation, "side": side, "factor": index}
    if factor.var is not None:
        return factor.var, (0, 0, 0, 0)
    try:
        quantity = parse_expression(factor.unit)
    except UnitSyntaxError as exc:
        raise _unprocessable(
            "syntax_error", exc.message,
            field="unit", position=exc.position, **location)
    except OffsetScaleInCompoundError as exc:
        # 复合式中的 °C / °F 与单独出现一样，按“只取量纲”规则拒绝。
        raise _unprocessable(
            "offset_temperature_not_allowed",
            "offset temperature scales °C / °F are not allowed; use K instead",
            **location)
    if quantity.offset_unit is not None:
        raise _unprocessable(
            "offset_temperature_not_allowed",
            "offset temperature scales °C / °F are not allowed; use K instead",
            **location)
    return None, quantity.dims


@app.post("/infer-dimensions", response_model=InferDimensionsResponse)
def infer_dimensions_endpoint(
    req: InferDimensionsRequest,
) -> InferDimensionsResponse:
    equations: list[ProductEquation] = []
    seen_vars: set[str] = set()

    for eq_i, eq in enumerate(req.equations):
        coeffs: dict[str, int] = {}
        rhs = [0, 0, 0, 0]
        for side, factors in (("left", eq.left), ("right", eq.right)):
            for j, factor in enumerate(factors):
                name, dims = _factor_dims(factor, eq_i, side, j)
                sign = 1 if side == "left" else -1
                if name is not None:
                    seen_vars.add(name)
                    coeffs[name] = coeffs.get(name, 0) + sign * factor.power
                else:
                    for dim in range(4):
                        rhs[dim] -= sign * factor.power * dims[dim]
        equations.append(ProductEquation(coeffs, tuple(rhs)))

    if not seen_vars:
        raise _unprocessable(
            "no_variables",
            "at least one factor with 'var' is required")

    try:
        result = infer_dimensions(equations)
    except InferenceError as exc:
        raise _unprocessable(exc.kind, exc.message, **exc.extra)

    return InferDimensionsResponse(dimensions={
        name: DimensionModel(
            length=dims[0], mass=dims[1], time=dims[2], temperature=dims[3])
        for name, dims in result.items()
    })


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

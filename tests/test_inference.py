"""量纲推断核心逻辑测试（不经过 HTTP）。"""

import pytest

from app.inference import (
    FRACTIONAL,
    INCONSISTENT,
    UNDERDETERMINED,
    InferenceError,
    ProductEquation,
    infer_dimensions,
)


def eq(left_vars, right_vars, rhs=(0, 0, 0, 0)):
    """便捷构造：left_vars/right_vars 为 {变量: 幂} 或 [变量]。"""
    def as_map(spec):
        if isinstance(spec, dict):
            return spec
        return {name: 1 for name in spec}
    coeffs = dict(as_map(left_vars))
    for name, p in as_map(right_vars).items():
        coeffs[name] = coeffs.get(name, 0) - p
    return ProductEquation(coeffs, rhs)


def test_single_equation_basic():
    # F = kg*m/s^2
    result = infer_dimensions([
        eq({"F": 1}, {}, rhs=(1, 1, -2, 0)),
    ])
    assert result == {"F": (1, 1, -2, 0)}


def test_newton_system_across_equations():
    # x = m；t = s；m = kg；v*t = x；a*t = v；F = m*a
    result = infer_dimensions([
        eq({"x": 1}, {}, rhs=(1, 0, 0, 0)),
        eq({"t": 1}, {}, rhs=(0, 0, 1, 0)),
        eq({"m": 1}, {}, rhs=(0, 1, 0, 0)),
        eq({"v": 1, "t": 1}, {"x": 1}),
        eq({"a": 1, "t": 1}, {"v": 1}),
        eq({"F": 1}, {"m": 1, "a": 1}),
    ])
    assert result == {
        "F": (1, 1, -2, 0),
        "a": (1, 0, -2, 0),
        "m": (0, 1, 0, 0),
        "t": (0, 0, 1, 0),
        "v": (1, 0, -1, 0),
        "x": (1, 0, 0, 0),
    }
    # 按变量名排序
    assert list(result) == ["F", "a", "m", "t", "v", "x"]


def test_powers_merged():
    # x*x = m^2，幂次须先合并：x = m
    result = infer_dimensions([
        eq({"x": 2}, {}, rhs=(2, 0, 0, 0)),
    ])
    assert result == {"x": (1, 0, 0, 0)}


def test_negative_integer_solution():
    # t = s；v*t = m  →  v = m/t（时间指数为 -1）
    result = infer_dimensions([
        eq({"t": 1}, {}, rhs=(0, 0, 1, 0)),
        eq({"v": 1, "t": 1}, {}, rhs=(1, 0, 0, 0)),
    ])
    assert result == {"t": (0, 0, 1, 0), "v": (1, 0, -1, 0)}


def test_dimensionless_solution():
    # a*a = 1（无单位 RHS）→ a 无量纲
    result = infer_dimensions([
        eq({"a": 2}, {}),
    ])
    assert result == {"a": (0, 0, 0, 0)}


def test_temperature_dimension():
    # E = K*s  →  E 量纲为时间*温度
    result = infer_dimensions([
        eq({"E": 1}, {}, rhs=(0, 0, 1, 1)),
    ])
    assert result == {"E": (0, 0, 1, 1)}


def test_inconsistent_constraints():
    # x = m 与 x = s 矛盾
    with pytest.raises(InferenceError) as exc:
        infer_dimensions([
            eq({"x": 1}, {}, rhs=(1, 0, 0, 0)),
            eq({"x": 1}, {}, rhs=(0, 0, 1, 0)),
        ])
    assert exc.value.kind == INCONSISTENT


def test_inconsistent_unit_only_equation():
    # m = s：无变量的单位行矛盾
    with pytest.raises(InferenceError) as exc:
        infer_dimensions([eq({}, {}, rhs=(1, 0, -1, 0))])
    assert exc.value.kind == INCONSISTENT


def test_inconsistent_takes_priority_over_underdetermined():
    # x 欠定，但同时 m = kg 矛盾；应先报矛盾
    with pytest.raises(InferenceError) as exc:
        infer_dimensions([
            eq({"x": 1}, {"x": 1}),
            eq({}, {}, rhs=(1, -1, 0, 0)),
        ])
    assert exc.value.kind == INCONSISTENT


def test_underdetermined_missing_equation():
    # F = m*a，无其它等式：F、a 可沿长度方向自由取值
    with pytest.raises(InferenceError) as exc:
        infer_dimensions([eq({"F": 1}, {"m": 1, "a": 1})])
    assert exc.value.kind == UNDERDETERMINED


def test_underdetermined_var_in_zero_coefficient_equation():
    # x 被完全消去（m = m），x 从未受约束
    with pytest.raises(InferenceError) as exc:
        infer_dimensions([eq({"x": 1}, {"x": 1})])
    assert exc.value.kind == UNDERDETERMINED


def test_redundant_equation_conflicting_in_another_dimension():
    # x = kg*m/s^2；2x = m^2：长度维一致（x=1），质量维却要求 x=1 与 x=0
    with pytest.raises(InferenceError) as exc:
        infer_dimensions([
            eq({"x": 1}, {}, rhs=(1, 1, -2, 0)),
            eq({"x": 2}, {}, rhs=(2, 0, 0, 0)),
        ])
    assert exc.value.kind == INCONSISTENT


def test_unmentioned_dimensions_resolve_to_zero():
    # 系数矩阵满秩时，未被任何单位提及的维度唯一解为 0：x = kg
    result = infer_dimensions([eq({"x": 1}, {}, rhs=(0, 1, 0, 0))])
    assert result == {"x": (0, 1, 0, 0)}


def test_fractional_exponents():
    # 2x = m 唯一解为 x = m^(1/2)
    with pytest.raises(InferenceError) as exc:
        infer_dimensions([eq({"x": 2}, {}, rhs=(1, 0, 0, 0))])
    assert exc.value.kind == FRACTIONAL
    assert exc.value.extra["variable"] == "x"
    assert exc.value.extra["dimension"] == "length"


def test_fractional_from_multi_equation_system():
    # x*y = m^2；x/y = 1 → x = y = m（整数解）
    result = infer_dimensions([
        eq({"x": 1, "y": 1}, {}, rhs=(2, 0, 0, 0)),
        eq({"x": 1, "y": -1}, {}),
    ])
    assert result == {"x": (1, 0, 0, 0), "y": (1, 0, 0, 0)}

    # x*y = m；x/y = 1 → x = y = m^(1/2)
    with pytest.raises(InferenceError) as exc:
        infer_dimensions([
            eq({"x": 1, "y": 1}, {}, rhs=(1, 0, 0, 0)),
            eq({"x": 1, "y": -1}, {}),
        ])
    assert exc.value.kind == FRACTIONAL

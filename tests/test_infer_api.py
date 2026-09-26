"""POST /infer-dimensions 的 HTTP API 测试。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def infer(equations):
    return client.post("/infer-dimensions", json={"equations": equations})


def fvar(name, power=1):
    return {"var": name, "power": power}


def funit(expr, power=1):
    return {"unit": expr, "power": power}


# ---------------------------------------------------------------- 成功用例

def test_infer_newton():
    # x = m；t = s；m = kg；v*t = x；a*t = v；F = m*a
    r = infer([
        {"left": [fvar("x")], "right": [funit("m")]},
        {"left": [fvar("t")], "right": [funit("s")]},
        {"left": [fvar("m")], "right": [funit("kg")]},
        {"left": [fvar("v"), fvar("t")], "right": [fvar("x")]},
        {"left": [fvar("a"), fvar("t")], "right": [fvar("v")]},
        {"left": [fvar("F")], "right": [fvar("m"), fvar("a")]},
    ])
    assert r.status_code == 200
    dims = r.json()["dimensions"]
    assert dims == {
        "F": {"length": 1, "mass": 1, "time": -2, "temperature": 0},
        "a": {"length": 1, "mass": 0, "time": -2, "temperature": 0},
        "m": {"length": 0, "mass": 1, "time": 0, "temperature": 0},
        "t": {"length": 0, "mass": 0, "time": 1, "temperature": 0},
        "v": {"length": 1, "mass": 0, "time": -1, "temperature": 0},
        "x": {"length": 1, "mass": 0, "time": 0, "temperature": 0},
    }
    # 按变量名排序
    assert list(dims) == ["F", "a", "m", "t", "v", "x"]


def test_infer_default_power_is_one():
    r = infer([
        {"left": [fvar("x")], "right": [funit("m")]},
    ])
    assert r.status_code == 200
    assert r.json()["dimensions"]["x"] == {
        "length": 1, "mass": 0, "time": 0, "temperature": 0}


def test_infer_merged_powers():
    # x*x / m^2 = 1
    r = infer([
        {"left": [fvar("x", 2)], "right": [funit("m", 2)]},
    ])
    assert r.status_code == 200
    assert r.json()["dimensions"]["x"]["length"] == 1


def test_infer_repeated_var_in_one_side():
    # t = s；v*t*v = m^2/s  →  2v + t = (2,0,-1)，故 v=(1,0,-1)、t=(0,0,1)
    r = infer([
        {"left": [fvar("t")], "right": [funit("s")]},
        {"left": [fvar("v"), fvar("t"), fvar("v")],
         "right": [funit("m", 2), funit("s", -1)]},
    ])
    assert r.status_code == 200
    dims = r.json()["dimensions"]
    assert dims["v"] == {"length": 1, "mass": 0, "time": -1, "temperature": 0}
    assert dims["t"] == {"length": 0, "mass": 0, "time": 1, "temperature": 0}


def test_infer_unit_expressions_and_zero_power():
    # E = kg*m^2/s^2（焦耳）
    r = infer([
        {"left": [fvar("E")],
         "right": [funit("kg"), funit("m", 2), funit("s", -2)]},
    ])
    assert r.status_code == 200
    assert r.json()["dimensions"]["E"] == {
        "length": 2, "mass": 1, "time": -2, "temperature": 0}


def test_infer_kelvin_allowed():
    r = infer([
        {"left": [fvar("q")], "right": [funit("K")]},
    ])
    assert r.status_code == 200
    assert r.json()["dimensions"]["q"]["temperature"] == 1


def test_infer_dimensionless_variable():
    # k*k = m/m（无量纲）
    r = infer([
        {"left": [fvar("k"), fvar("k")], "right": [funit("m"), funit("m", -1)]},
    ])
    assert r.status_code == 200
    assert r.json()["dimensions"]["k"] == {
        "length": 0, "mass": 0, "time": 0, "temperature": 0}


def test_infer_power_zero_does_not_bind_variable():
    # x^0 = m/m（RHS 无量纲），x 完全不受约束
    r = infer([
        {"left": [fvar("x", 0)], "right": [funit("m"), funit("m", -1)]},
    ])
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "underdetermined_constraints"


# ---------------------------------------------------------------- 422 错误

def test_infer_inconsistent():
    r = infer([
        {"left": [fvar("x")], "right": [funit("m")]},
        {"left": [fvar("x")], "right": [funit("s")]},
    ])
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "inconsistent_constraints"
    assert "dimension" in detail


def test_infer_underdetermined():
    r = infer([
        {"left": [fvar("F")], "right": [fvar("m"), fvar("a")]},
    ])
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "underdetermined_constraints"


def test_infer_fractional():
    r = infer([
        {"left": [fvar("x", 2)], "right": [funit("m")]},
    ])
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "fractional_exponents"
    assert detail["variable"] == "x"
    assert detail["dimension"] == "length"


def test_infer_no_variables():
    r = infer([
        {"left": [funit("m")], "right": [funit("m")]},
    ])
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "no_variables"


def test_infer_offset_temperature_rejected():
    for expr in ("°C", "°F"):
        r = infer([
            {"left": [fvar("x")], "right": [funit(expr)]},
        ])
        assert r.status_code == 422, expr
        detail = r.json()["detail"]
        assert detail["error"] == "offset_temperature_not_allowed", expr
        assert detail["equation"] == 0
        assert detail["side"] == "right"
        assert detail["factor"] == 0


def test_infer_offset_temperature_in_compound_rejected():
    r = infer([
        {"left": [fvar("x")], "right": [funit("°C/s")]},
    ])
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "offset_temperature_not_allowed"


def test_infer_unit_syntax_error_has_location():
    r = infer([
        {"left": [fvar("x")], "right": [{"unit": "m s"}]},
    ])
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "syntax_error"
    assert detail["field"] == "unit"
    assert detail["position"] == 2
    assert detail["equation"] == 0
    assert detail["side"] == "right"
    assert detail["factor"] == 0


# ---------------------------------------------------------------- 请求结构校验（FastAPI → 422）

def test_infer_missing_equations():
    assert client.post("/infer-dimensions", json={}).status_code == 422


def test_infer_empty_equations():
    assert infer([]).status_code == 422


def test_infer_empty_side():
    assert infer([{"left": [], "right": [funit("m")]}]).status_code == 422
    assert infer([{"left": [fvar("x")], "right": []}]).status_code == 422


def test_infer_factor_requires_exactly_one_kind():
    # 两者都有
    assert infer([
        {"left": [{"var": "x", "unit": "m"}], "right": [funit("m")]},
    ]).status_code == 422
    # 两者都无
    assert infer([
        {"left": [{"power": 1}], "right": [funit("m")]},
    ]).status_code == 422


def test_infer_power_out_of_range():
    assert infer([
        {"left": [fvar("x", 7)], "right": [funit("m")]},
    ]).status_code == 422
    assert infer([
        {"left": [fvar("x", -7)], "right": [funit("m")]},
    ]).status_code == 422


def test_infer_power_must_be_integer():
    assert infer([
        {"left": [{"var": "x", "power": 0.5}], "right": [funit("m")]},
    ]).status_code == 422


def test_infer_extra_field_rejected():
    assert infer([
        {"left": [{"var": "x", "note": "?"}], "right": [funit("m")]},
    ]).status_code == 422


def test_infer_blank_var_rejected():
    assert infer([
        {"left": [{"var": "  "}], "right": [funit("m")]},
    ]).status_code == 422

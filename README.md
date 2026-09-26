# 单位换算 API（Unit Converter）

基于 **Python + FastAPI + Decimal/Fraction** 的工程单位换算服务。
支持长度、质量、时间、温度四维量纲核对，复合单位表达式，以及 °C / °F 偏移温标换算；
还能依据多条乘积等式推断未知变量的四维量纲（`POST /infer-dimensions`）。

## 启动（单条命令）

```bash
docker compose up --build
```

启动后本机访问：

- API 地址：**http://localhost:8000**
- 交互式文档（Swagger UI）：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

## API

### POST /convert

请求体（JSON，`value` 为有限十进制字符串）：

```json
{
  "value": "36",
  "from": "km/h",
  "to": "m/s"
}
```

响应（`result` 为字符串）：

```json
{"result": "10"}
```

示例：

```bash
curl -X POST http://localhost:8000/convert \
  -H 'Content-Type: application/json' \
  -d '{"value": "100", "from": "°C", "to": "°F"}'
# {"result":"212"}
```

### POST /infer-dimensions

依据多条**乘积等式**推断未知变量的四维（长度 / 质量 / 时间 / 温度）整数量纲。
请求体含 `equations`，每条等式的 `left`、`right` 都是**非空因子数组**；
因子恰有 `var`（未知变量名）或 `unit`（单位表达式）一个字段，
并可带 `-6～6` 的整数 `power`（默认 `1`）。全部等式中至少出现一个 `var`。
`unit` 复用 `/convert` 的单位表达式解析器、**只取量纲**（比例被忽略），
偏移温标 `°C` / `°F` 一律拒绝，需要温度维时请用 `K`。

跨等式合并同名变量的幂次后，每个维度构成一个独立线性方程组。
仅当每个变量的四维指数都存在**唯一整数解**时才返回结果：

```bash
curl -X POST http://localhost:8000/infer-dimensions \
  -H 'Content-Type: application/json' \
  -d '{
    "equations": [
      {"left": [{"var": "x"}], "right": [{"unit": "m"}]},
      {"left": [{"var": "t"}], "right": [{"unit": "s"}]},
      {"left": [{"var": "M"}], "right": [{"unit": "kg"}]},
      {"left": [{"var": "v"}, {"var": "t"}], "right": [{"var": "x"}]},
      {"left": [{"var": "a"}, {"var": "t"}], "right": [{"var": "v"}]},
      {"left": [{"var": "F"}], "right": [{"var": "M"}, {"var": "a"}]}
    ]
  }'
```

响应（`dimensions` 按变量名排序，逐项列出四维指数）：

```json
{
  "dimensions": {
    "F": {"length": 1, "mass": 1, "time": -2, "temperature": 0},
    "M": {"length": 0, "mass": 1, "time": 0, "temperature": 0},
    "a": {"length": 1, "mass": 0, "time": -2, "temperature": 0},
    "t": {"length": 0, "mass": 0, "time": 1, "temperature": 0},
    "v": {"length": 1, "mass": 0, "time": -1, "temperature": 0},
    "x": {"length": 1, "mass": 0, "time": 0, "temperature": 0}
  }
}
```

因子示例：`{"var": "x", "power": 2}` 表示 x²；`{"unit": "m", "power": -1}`
表示 m⁻¹；`{"unit": "kg*m/s^2"}` 这样的复合表达式同样合法（只取其量纲）。

## 单位与表达式语法

- 支持单位：`m`、`km`、`cm`、`mm`（长度）；`kg`、`g`（质量）；`s`、`min`、`h`（时间）；`K`、`°C`、`°F`（温度）。
- 表达式允许：括号 `()`、乘法 `*`、除法 `/`，以及 `^` 后的 **-6～6 整数幂**（如 `m^2`、`s^-2`）。
- 忽略空白；**不允许隐式乘法**（`m s`、`2m`、`m(kg)` 均为语法错误）。
- 量纲按（长度、质量、时间、温度）四维核对，`from` 与 `to` 量纲必须一致；比例用有理数精确累计。
- `°C`、`°F` 为偏移温标，**只允许单独使用**（可套括号，如 `(°C)`），不得参与 `*`、`/`、`^` 复合运算；换算先经 K（`°C + 273.15 = K`，`(°F + 459.67) × 5/9 = K`）。复合式中的 `K` 只按比例处理。
- 结果按 **ROUND_HALF_EVEN** 保留最多 **12 位小数**，并去掉末尾零（如 `2.50` → `2.5`，`1/3` → `0.333333333333`）。

## 错误响应（均为 422）

语法错误返回从 **0** 开始的字符位置：

```json
{
  "detail": {
    "error": "syntax_error",
    "message": "unexpected 's' (missing operator; implicit multiplication is not allowed)",
    "field": "from",
    "position": 2
  }
}
```

| `error` | 含义 |
| --- | --- |
| `syntax_error` | 单位表达式语法错误，含 `field`（`from`/`to`，推断接口为 `unit`）与 0 起始的 `position` |
| `dimension_mismatch` | 两侧量纲不一致（`/convert`） |
| `offset_temperature_in_compound` | °C / °F 参与了复合运算（`/convert`） |
| `invalid_value` | `value` 不是有限十进制字符串（`/convert`） |
| `no_variables` | `/infer-dimensions` 的全部因子都是 `unit`，至少需要一个 `var` |
| `inconsistent_constraints` | `/infer-dimensions` 约束互相矛盾（含 `dimension`） |
| `underdetermined_constraints` | `/infer-dimensions` 约束不足，至少一个变量的指数不能唯一确定 |
| `fractional_exponents` | `/infer-dimensions` 唯一解含分数指数（含 `variable`、`dimension`），不接受 |
| `offset_temperature_not_allowed` | `/infer-dimensions` 的单位因子使用了 °C / °F（只取量纲，请改用 K）；含 `equation`、`side`、`factor` 定位 |

`/infer-dimensions` 中单位因子的 `syntax_error` / `offset_temperature_not_allowed`
还会带上 `equation`（等式下标，从 0 开始）、`side`（`left`/`right`）与
`factor`（因子下标，从 0 开始）便于定位。推断错误的优先级为
矛盾 > 欠定 > 分数指数。

请求体缺字段、类型错误等由 FastAPI 校验，同样返回 422。

## 本地开发（不用 Docker）

```bash
pip install -r requirements-dev.txt
python -m pytest            # 运行测试
uvicorn app.main:app --reload --port 8000
```

## 项目结构

```
app/
  converter.py   # 词法/语法分析、量纲核对、有理数换算、ROUND_HALF_EVEN 格式化
  inference.py   # 乘积等式合并、四维 Fraction 高斯-若尔当消元、矛盾/欠定/分数判定
  main.py        # FastAPI 应用（POST /convert、POST /infer-dimensions、GET /health）
tests/           # pytest 测试（核心逻辑 + HTTP API）
Dockerfile
docker-compose.yml
requirements.txt / requirements-dev.txt
```

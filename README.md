# 单位换算 API（Unit Converter）

基于 **Python + FastAPI + Decimal/Fraction** 的工程单位换算服务。
支持长度、质量、时间、温度四维量纲核对，复合单位表达式，°C / °F 偏移温标换算，
以及由多条乘积等式推断未知变量的四维量纲。

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

依据多条乘积等式推断未知变量的（长度、质量、时间、温度）四维量纲。
请求体含 `equations` 数组；每条等式有非空因子数组 `left`、`right`，
因子恰含 `var`（未知变量名）或 `unit`（单位表达式）一个字段，
可带 **-6～6 的整数 `power`**（默认 1）；所有等式中至少出现一个 `var`。

把各因子的幂次合并后，每条等式在四个维度上各给出一个线性约束，跨等式组成
有理系数线性方程组。仅当每个变量的四个指数都有**唯一整数解**时返回结果，
`dimensions` 按变量名排序：

```json
{
  "equations": [
    {"left": [{"var": "F"}], "right": [{"var": "m"}, {"var": "a"}]},
    {"left": [{"var": "a"}], "right": [{"unit": "m/s^2"}]},
    {"left": [{"var": "m"}], "right": [{"unit": "kg"}]}
  ]
}
```

响应：

```json
{
  "dimensions": {
    "F": {"length": 1, "mass": 1, "time": -2, "temperature": 0},
    "a": {"length": 1, "mass": 0, "time": -2, "temperature": 0},
    "m": {"length": 0, "mass": 1, "time": 0, "temperature": 0}
  }
}
```

示例：

```bash
curl -X POST http://localhost:8000/infer-dimensions \
  -H 'Content-Type: application/json' \
  -d '{"equations":[{"left":[{"var":"v"}],"right":[{"unit":"m/s"}]}]}'
# {"dimensions":{"v":{"length":1,"mass":0,"time":-1,"temperature":0}}}
```

单位因子复用单位表达式解析器但**只取量纲**，因此不接受 `°C` / `°F`
（偏移温标没有唯一的乘性量纲），请改用 `K`。约束矛盾、欠定或唯一解含
分数指数时均返回 422，并以不同的 `error` 区分（见下表）。

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
| `syntax_error` | 单位表达式语法错误，含 `field`（`from`/`to`）与 0 起始的 `position` |
| `dimension_mismatch` | 两侧量纲不一致 |
| `offset_temperature_in_compound` | °C / °F 参与了复合运算 |
| `invalid_value` | `value` 不是有限十进制字符串 |
| `no_variable` | `/infer-dimensions` 的所有等式中没有任何 `var` 因子 |
| `inconsistent_constraints` | 约束互相矛盾（如同一变量同时被约束为 `m` 与 `s`），含首个矛盾维度 `dimension` |
| `underdetermined` | 约束不足，存在无法唯一确定的变量，含 `free_variables` 列表 |
| `fractional_dimensions` | 解唯一但含分数指数（如 `x^2 = m`），含相关 `variables` 列表 |
| `offset_temperature_not_allowed` | `/infer-dimensions` 的单位因子使用了 °C / °F；含 `equation`、`side`、`factor` 坐标（及单位表达式内 `position`） |

`/infer-dimensions` 的单位因子语法错误同样返回 `syntax_error`，并带
`equation`（等式下标）、`side`（`left`/`right`）、`factor`（因子下标）
与 0 起始的 `position`。

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
  dimensions.py  # 跨等式线性约束（有理 Gauss-Jordan 消元）与四维量纲推断
  main.py        # FastAPI 应用（POST /convert、POST /infer-dimensions、GET /health）
tests/           # pytest 测试（核心逻辑 + HTTP API）
Dockerfile
docker-compose.yml
requirements.txt / requirements-dev.txt
```

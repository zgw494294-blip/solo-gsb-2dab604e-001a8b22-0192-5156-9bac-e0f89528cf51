# 单位换算 API（Unit Converter）

基于 **Python + FastAPI + Decimal/Fraction** 的工程单位换算服务。
支持长度、质量、时间、温度四维量纲核对，复合单位表达式，以及 °C / °F 偏移温标换算。

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
  main.py        # FastAPI 应用（POST /convert、GET /health）
tests/           # pytest 测试（核心逻辑 + HTTP API）
Dockerfile
docker-compose.yml
requirements.txt / requirements-dev.txt
```

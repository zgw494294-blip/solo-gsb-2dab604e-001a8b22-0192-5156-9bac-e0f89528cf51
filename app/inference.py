"""依据多条乘积等式推断未知变量的四维量纲。

每条等式两边都是若干因子的乘积（因子带 -6～6 的整数幂），合并同变量的
幂次后得到一条线性方程：

    Σ_left  dims(factor) = Σ_right dims(factor)

单位因子的四维指数已知，变量在（长度、质量、时间、温度）四维上的指数
未知，因此四个维度各自构成一个独立的线性方程组。对每一维用
``Fraction`` 做高斯-若尔当消元：

- 出现 0 = 非零 的矛盾行       → 约束矛盾（inconsistent）；
- 主元列数少于变量数（有自由变量）→ 欠定（underdetermined）；
- 唯一解但某个变量的指数不是整数 → 含分数指数（fractional）。

三种情况都无法给出“每个变量四维唯一整数解”，抛 :class:`InferenceError`。
错误优先级：矛盾 > 欠定 > 分数指数。
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .converter import DIM_NAMES

# 四个维度的错误类型，供 API 层映射为 422 detail.error
INCONSISTENT = "inconsistent_constraints"
UNDERDETERMINED = "underdetermined_constraints"
FRACTIONAL = "fractional_exponents"


class InferenceError(Exception):
    """量纲推断失败；``kind`` 为错误类型，``extra`` 为附加定位信息。"""

    def __init__(self, kind: str, message: str, **extra):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.extra = extra


@dataclass(frozen=True)
class ProductEquation:
    """一条合并后的线性方程：Σ coeffs[var]·x_var = rhs（逐维成立）。

    ``coeffs`` 为变量在“左正右负”约定下合并的净幂次；
    ``rhs`` 为右侧单位指数和减去左侧单位指数和的四维向量。
    """

    coeffs: dict[str, int]
    rhs: tuple[int, int, int, int]


def _solve_dimension(
    matrix: list[list[int]], rhs: list[int]
) -> tuple[str, list[Fraction] | None]:
    """对单个维度做增广矩阵的高斯-若尔当消元（RREF）。

    返回 ``(status, solution)``：status 为
    ``"unique" | "inconsistent" | "underdetermined"``；
    仅当唯一解时 solution 为按列序排列的有理数向量。
    """
    m = len(matrix)
    n = len(matrix[0]) if m else 0
    table = [
        [Fraction(v) for v in matrix[i]] + [Fraction(rhs[i])]
        for i in range(m)
    ]

    pivot_cols: list[int] = []
    row = 0
    for col in range(n):
        pivot = next((i for i in range(row, m) if table[i][col] != 0), None)
        if pivot is None:
            continue
        table[row], table[pivot] = table[pivot], table[row]
        scale = table[row][col]
        table[row] = [v / scale for v in table[row]]
        for i in range(m):
            if i != row and table[i][col] != 0:
                factor = table[i][col]
                table[i] = [
                    a - factor * b for a, b in zip(table[i], table[row])
                ]
        pivot_cols.append(col)
        row += 1

    # 主元行以下若残留 0 系数 = 非零常数，则方程组矛盾。
    for i in range(row, m):
        if table[i][n] != 0:
            return "inconsistent", None

    if len(pivot_cols) < n:
        return "underdetermined", None

    pivot_row = {col: i for i, col in enumerate(pivot_cols)}
    return "unique", [table[pivot_row[col]][n] for col in range(n)]


def infer_dimensions(
    equations: list[ProductEquation],
) -> dict[str, tuple[int, int, int, int]]:
    """推断各变量的四维整数指数；无法唯一确定时抛 :class:`InferenceError`。"""
    names = sorted({name for eq in equations for name in eq.coeffs})
    index = {name: i for i, name in enumerate(names)}
    n_vars = len(names)

    matrix = [[0] * n_vars for _ in equations]
    for i, eq in enumerate(equations):
        for name, coef in eq.coeffs.items():
            matrix[i][index[name]] = coef

    solutions: dict[int, list[Fraction]] = {}
    underdetermined = False
    fractional: list[tuple[str, str]] = []

    for dim, dim_name in enumerate(DIM_NAMES):
        rhs = [eq.rhs[dim] for eq in equations]
        status, solution = _solve_dimension(matrix, rhs)
        if status == "inconsistent":
            raise InferenceError(
                INCONSISTENT,
                f"equations are contradictory in the {dim_name} dimension",
                dimension=dim_name,
            )
        if status == "underdetermined":
            # 继续检查其余维度是否矛盾；矛盾优先于欠定上报。
            underdetermined = True
            continue
        solutions[dim] = solution
        if not underdetermined:
            for name in names:
                value = solution[index[name]]
                if value.denominator != 1:
                    fractional.append((name, dim_name))

    if underdetermined:
        raise InferenceError(
            UNDERDETERMINED,
            "constraints are underdetermined: at least one variable's "
            "exponents are not uniquely fixed; more equations are needed",
        )

    if fractional:
        name, dim_name = fractional[0]
        raise InferenceError(
            FRACTIONAL,
            f"unique solution requires a fractional {dim_name} exponent "
            f"for variable {name!r}; only integer exponents are accepted",
            variable=name,
            dimension=dim_name,
        )

    return {
        name: tuple(
            solutions[dim][index[name]].numerator for dim in range(4)
        )
        for name in names
    }

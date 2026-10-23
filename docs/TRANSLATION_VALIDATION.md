# 翻译文本校验规则

本项目使用 `text`、`evs` 和 `eboot` 三种检查类型。三种类型共享一组通用规则，
`evs` 和 `eboot` 还会执行各自的二进制或运行时限制检查。

规则实现位于 `scripts/paratranz/validation.py`。文件发现、JSON 读取和报告生成位于
`scripts/check.py`。

## 快速使用

检查一个普通文本文件：

```sh
uv run python -m scripts.check tev.json build/tev_report.json text
```

只执行 `format_markers` 规则：

```sh
uv run python -m scripts.check tev.json build/tev_report.json text \
  --rule format_markers
```

`--rule` 可以重复使用。以下命令只检查运行时标记和编码：

```sh
uv run python -m scripts.check tev.json build/tev_report.json text \
  --rule format_markers \
  --rule encoding
```

未提供 `--rule` 时执行该类型适用的全部规则。输入条目结构检查始终执行，不受规则筛选
影响。

检查 EVS 或 EBOOT 文件时，将最后一个参数分别改为 `evs` 或 `eboot`：

```sh
uv run python -m scripts.check evs.json build/evs_report.json evs
uv run python -m scripts.check eboot.json build/eboot_report.json eboot
```

默认情况下，发现翻译问题仍返回退出码 `0`，问题记录在报告中。CI 或脚本需要在发现
问题时失败，可增加 `--strict`：

```sh
uv run python -m scripts.check tev.json build/tev_report.json text --strict
```

检查下载目录内的全部标准翻译文件：

```sh
make check_trans
```

报告默认写入 `build/translation_report.json`。

## 类型总览

| 检查类型 | 通用文本规则 | 专属规则 | 主要用途 |
| --- | --- | --- | --- |
| `text` | 全部执行 | 无 | TEXT、BIND、MemTalk 等普通文本 |
| `evs` | 全部执行 | `paging` | EVS 对话及分页文本 |
| `eboot` | 全部执行 | `eboot_length` | EBOOT 中的定长字符串替换 |

选择类型只决定是否增加专属规则。它不会关闭编码、格式标记、术语或中文样式等通用
规则。

## 通用规则

以下规则对 `text`、`evs` 和 `eboot` 全部生效。

| 规则 ID | 级别 | 检查内容 |
| --- | --- | --- |
| `format_markers` | error | 原文和译文中的运行时标记必须种类、数量完全一致。当前识别 `%s`、`%02d`、`$m`、`$n`、`▽` 等形式。 |
| `line_breaks` | warning | 实际换行符和字面量 `\n` 的数量与原文不一致时给出提示，但不视为硬错误。 |
| `encoding` | error | 译文必须能通过项目的 EVA Shift-JIS 字符映射编码。 |
| `fullwidth_digits` | warning | 译文中不得出现全角数字 `０` 至 `９`。 |
| `length_ratio` | warning | 译文字符数不得超过原文字符数的两倍。此规则比较字符数，不比较编码后的字节数。 |
| `terminology` | warning | 原文命中术语或术语变体时，译文必须包含至少一个允许译法。匹配为区分大小写的字面子串匹配。 |
| `ellipsis_style` | error / warning | 禁止 `...`、`…?`、`…？`，以及省略号紧邻逗号或句号。原文和译文都只有单个 `…` 时给出 warning，建议使用 `……`。 |
| `fullwidth_tilde` | error | 禁止 ASCII `~`，应使用全角 `～`。 |
| `dash_style` | error | 译文引入的 ASCII `-` 数量不得超过原文；中文破折号应使用 `—`。 |
| `cjk_latin_spacing` | error | 禁止在中文字符与英文字母或数字之间插入半角空格。 |
| `corner_quotes` | error | 禁止 ASCII 双引号和中英文弯引号 `“”‘’`，项目统一使用 `「」`。 |
| `eva_special_characters` | error | `Θ`、`Α`、`Τ`、`Ν`、`Σ`、`Ｓ` 的种类和数量必须与原文一致。 |
| `invisible_characters` | error | 除 CR/LF 外的 Unicode 控制字符和格式字符必须按种类、数量保留。 |
| `layout_spaces` | warning | 原文中连续两个或更多半角空格形成的布局区段，应尽量在译文中保留。 |

一条译文可能同时触发多条规则。例如，`中文 text...` 会同时触发
`cjk_latin_spacing` 和 `ellipsis_style`。

## EVS 专属规则

### `paging`

`evs` 类型会按 `▽` 拆分页面，再按 `$n` 拆分页面内的文本段。每段使用 EVA
Shift-JIS 编码后：

1. 去掉半角空格和实际换行符；
2. 加上一个 `▽` 标记的编码长度；
3. 与 `CONTENT_BYTE_LIMIT` 比较。

编码长度大于或等于限制时产生 `error`。报告会包含页码、`$n` 段号、实际字节数和
文本预览。

`paging` 检查的是运行时字节限制，与通用的 `length_ratio` 字符数提示不是同一件事。

## EBOOT 专属规则

### `eboot_length`

`eboot` 类型会分别计算原文和译文的 EVA Shift-JIS 编码长度：

| 译文相对原文的增量 | 结果 |
| --- | --- |
| 小于或等于 0 字节 | 通过 |
| 1 至 4 字节 | warning |
| 超过 4 字节 | error |

此规则用于发现可能超出 EBOOT 原始字符串空间的译文。

## 输入与跳过行为

单文件检查要求 JSON 顶层是数组，每个条目至少包含：

```json
{
  "key": "entry-id",
  "original": "source text",
  "translation": "translated text"
}
```

- `original` 必须是字符串。
- `translation` 必须是字符串或 `null`。
- `key` 可省略；报告会使用条目序号生成临时标识。
- 条目不是对象或字段类型错误时，产生 `entry_structure` error。
- 批量文件检查会跳过 `null` 或空字符串译文，并计入报告的 `skipped`，不会产生
  `empty_translation`。
- 重译工具在校验待写回的单条结果时不会跳过空值，而会产生
  `empty_translation` error。

## 批量文件类型映射

`make check_trans` 根据路径选择类型：

| 文件 | 类型 |
| --- | --- |
| `eboot_trans.json` | `eboot` |
| `evs_trans.json` | `evs` |
| `utf8/EVS/cev/**/*.json` | `evs` |
| `utf8/memtalk.json` | `text` |
| `utf8/free/**/*.json` | `text` |
| `utf8/game/**/*.json` | `text` |

## 增加规则

新增规则时，在 `scripts/paratranz/validation.py` 中使用注册器：

```python
@RULES.register("rule_name")
def check_rule_name(context: CheckContext) -> list[ValidationIssue]:
    if condition_is_valid(context):
        return []
    return [ValidationIssue("rule_name", "Actionable message", "error")]
```

仅对特定类型生效时传入 `check_types`：

```python
@RULES.register("evs_only_rule", check_types=("evs",))
```

每条新规则应在 `tests/test_translation_validation.py` 增加通过和失败用例。如果规则涉及
编码长度、分页或运行时标记，还应覆盖对应资源类型，避免只验证普通 `text`。

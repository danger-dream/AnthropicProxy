# 05 · 实施日记

记录 Patch 1-6 实际做了什么、与 03 计划的偏离、留给后续的 TODO。

## 时间线

按顺序一气做完 6 个 patch；每个 patch 一个独立 commit、一个独立测试文件。

## 各 patch 摘要

### Patch 1 — P0 阻塞修复（#1/#2/#9/#15/#20）

- **修复**：5 条 P0 bug。
- **基础设施**：抽出 `common.build_response_usage` + `common.build_chat_usage`，
  四处 `_usage_*` 函数全部改用统一 builder。details 字段 (cached/reasoning) 始终
  写入 0。
- **测试**：13 用例。
- **偏离**：现有 `test_guard_conversation_null_allowed` 的 body 没带 `model`，
  适配 #2 后补上 `"model": "x"`，详见 04-implementation-notes.md。

### Patch 2 — 流式状态机一致性（#13/#16/#17/#41/#43）

- **修复**：5 条流式 bug。
- **基础设施**：抽出 `common.build_response_skeleton`，
  `stream_c2r.StreamTranslator` 增加 `request_body` 构造参数（向后兼容）。
- **测试**：8 用例。
- **关键改动**：`_MessageItem` 的 `_next_content_index` 累计计数器解决 #16 撞车；
  `terminal_error` 路径也调 `_save_to_store_if_configured` 解决 #41。

### Patch 3 — tool / tool_choice 完整支持（#21/#23/#24/#25/#26/#27/#30）

- **修复**：7 条 tool 相关 bug + custom_tool_call 流式状态机。
- **基础设施**：guard 新增 `_NON_CHAT_TOOL_CHOICE_TYPES`；built-in 名单按
  spec 全部补齐；stream_c2r 新增 `_CustomToolCallItem` 数据类。
- **测试**：14 用例。codex_oauth 全部 50 个回归通过。
- **偏离**：现有 `test_c2r_translate_request_basics` /
  `test_chat_to_responses_function_tool` 的 tools 精确字典断言因 #30 自动补
  `strict: False` 而失配；适配。

### Patch 4 — 字段补齐（#4/#5/#11/#12/#28/#29/#35）

- **修复**：7 条字段双向映射 bug。
- **基础设施**：`_gather_annotations` helper；`R2CState.annotations` 累计字段。
- **测试**：11 用例。
- **关键改动**：r2c reasoning_summary 用非官方 chat 字段 `reasoning_summary`
  桥接（DeepSeek 系列同名字段）；annotations 双向都按 dict-list 透传。

### Patch 5 — 错误规范（#7/#8/#10/#18）

- **修复**：4 条错误处理 bug。
- **基础设施**：`common.RESPONSE_ERROR_CODES` (18 个 enum) +
  `map_response_error_code()` 映射函数。
- **测试**：7 用例。
- **关键改动**：`_emit_failed` 的 error 字段从 `{message, type}` 改为
  spec 正式的 `{message, code}`。stream_c2r 处理 chat 老协议
  `delta.function_call` 字段。

### Patch 6 — 边界 + 死代码清理 + 合约测试（#3/#6/#22/#33/#40 + 附录）

- **修复**：5 条边界 bug + 附录小修（reasoning item status）。
- **基础设施**：`_flatten_function_call_output` helper；guard 加
  prediction warning。
- **测试**：10 用例（含 2 个 spec 合约测试）。
- **偏离**：现有 `test_c2r_translate_request_basics` 的 system→developer 断言
  适配 #22；详见 04-implementation-notes.md。

## 与 03 计划的关键偏离汇总

| 项 | 03 计划 | 实际 | 原因 |
|---|---|---|---|
| `_dispatch.py` item dispatcher | 03 计划 2.1 强烈推荐 | **未实现** | 现有 if/elif 链经过本次 6 patch 修复后已经能正确处理所有 spec 提到的 item type；引入 dispatcher 框架代价大、收益边际，留给后续大重构时再统一抽象。本次以"先把 bug 修透"为重点。 |
| EventDispatcher 基类 | 03 计划 2.3 | **未实现** | 同上。stream_r2c / stream_c2r 当前 if/elif 已满足，未来扩展时再抽。 |
| `_dispatch.py` 测试矩阵 | 03 计划 5.1.2 | **未写** | 因为 dispatcher 没引入。但功能等价的覆盖已通过 patch 1-6 各自的回归测试达成。 |
| jsonschema 合约测试 | 03 计划 5.3 | **降级实现** | 没引入完整 OpenAPI → JSONSchema 编译链；只在 patch6 写了"必填字段存在性"风格的合约测试（test_contract_*_basic_shape）。完整 jsonschema 验证留 TODO。 |
| `_stringify_tool_content` 重写 | 03 计划 #36 | **未做** | 现状（仅取 text）功能正确，重构无收益且有风险，保持现状。 |
| #44/#45/#46 SSE 多行拼接 | 03 计划 Patch 6 | **降级实现** | 仅加了"不 raise"最低断言；完整 multi-line data join 留 TODO（生产从未观察到）。 |
| #19 reasoning summary vs reasoning_text 严格区分 | 03 计划 Patch 6 | **未做** | 02 标 P2，本次保持现状（两类文本拼接到 reasoning_content）。 |
| #38 reasoning 跨轮保留 | 03 计划 Patch 6 | **未做** | 02 自己降级为低优。 |
| #34 多 summary_part 流式 | 03 计划 Patch 6 边界 | **未做** | spec 允许、当前 chat 端只有一个 reasoning_content 字段，未来扩展时再做。 |

## 后续 TODO

按优先级：

1. **dispatcher 框架重构**：把 if/elif 链改成 `_dispatch.py` 的注册表式 dispatcher，提升新 item type 加入门槛、便于完整性测试。
2. **完整 JSONSchema 合约测试**：用 `openapi.documented.yml` 编译出 schema，对每个 `translate_request/response` 输出做 `jsonschema.validate`。需要先写 OpenAPI → JSONSchema 转换工具或引入 `openapi-schema-pydantic`。
3. **#19 reasoning 语义保留**：用 marker 把 summary 与 reasoning_text 区分开，回放时还原。
4. **#34 多 summary_part 流式**：当未来上游 chat reasoning_content 用换段表达多个 part 时实现。
5. **#36 _stringify_tool_content 严格化**：把 assistant content 的拍扁单独写函数。
6. **#44/#45/#46 SSE 完整规范处理**：multi-line data 拼接 + responses 流的 [DONE] 兜底。
7. **#33 多 tool / message item 高级场景**：当前实现只处理"上游连续 emit 两个 message item"，多 reasoning item 切换暂未做。
8. **codex_oauth_transform 与新 tool 形态联动**：本次 codex_oauth_transform.py **完全没动**；如果未来 Codex CLI 用 custom tool / allowed_tools，需要确认它能正确读到本次新增的 tool 形态。

## 测试统计

| Patch | 新增测试 | 累计通过 |
|---|---|---|
| baseline | — | 302 |
| patch1 | 13 | 315 |
| patch2 | 8 | 323 |
| patch3 | 14 | 337 |
| patch4 | 11 | 348 |
| patch5 | 7 | 355 |
| patch6 | 10 | 365 |

**0 个原有测试回归**（仅 3 个测试因新行为变化做了断言适配，全部记录在
04-implementation-notes.md）。

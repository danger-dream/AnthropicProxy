# 04 · 实施笔记 — 与 03 计划的偏离 / 实施期发现

## Patch 1

### 偏离 / 调整

1. **`test_openai_audit.py::test_guard_conversation_null_allowed` 测试更新（必要）**
   - 该测试为验证 conversation 字段的 null/空字典放行行为而构造了 `{"conversation": None}` 等极简 body，未带 `model`。
   - Patch 1 实现 #2（model required）后，guard 在到达 conversation 检查之前就会以 missing model 拒绝。
   - 修复方式：把测试 body 补上 `"model": "x", "input": []`；语义不变（仍然测 conversation 字段处理）。
   - 这是**已存在测试的最小适配**，不是新功能/不是行为回退。

### 补充说明

- `common.py` 同时新增了 `build_chat_usage`（与 `build_response_usage` 对称），使 chat-side 的 details 字段也始终写入。03 文档只提到 `build_response_usage`，但既然 02#9 要求"四处 _usage_* 全部改用此函数"，对称的 chat-side helper 是合理拓展，避免后续 patch 重复手抄。
- #20 的实现采用"`terminal_status` 一旦置位，下次 `feed` 进来的 event 全部短路"。03 的描述是"_on_completed/_on_incomplete 之后立即 set self.state.terminal_status 并 return；后续事件直接忽略"，本实现把忽略逻辑统一放在 `_handle_event_block` 入口，逻辑等价但更清晰。

## Patch 3

### 偏离 / 调整

1. **`test_openai_m3.py::test_c2r_translate_request_basics` 与 `test_chat_to_responses_function_tool` 测试更新（必要）**
   - 这两个测试断言 `out["tools"]` 与某个**精确字典**相等，未包含 `strict` 字段。
   - Patch 3 / #30 实现后，FunctionTool.strict 自动补默认 `False`，原断言因新增字段失配。
   - 修复：在期望字典里也加 `"strict": False`，注释指明 Patch 3 / #30。

### 设计说明

- `_BUILTIN_TOOL_TYPES` 名单按 02#21 全部补齐；`custom` **不**进 built-in 名单（它是用户定义工具），允许 translate 层正确处理。
- guard 新增 `_NON_CHAT_TOOL_CHOICE_TYPES` 集合用于 #25 的 tool_choice 预拦；MCP 等带 server_label 的也覆盖。
- stream_c2r 新增 `_CustomToolCallItem` 数据类与 `_handle_custom_tool_call_delta` 状态机，与 `_FunctionCallItem` 共享 output_index 顺序但事件名分别为 `response.custom_tool_call_input.delta/done`。
- 同 chat 流的 type=custom tool_call 与 type=function tool_call 通过 `tc.get("type") == "custom"` 在首包识别；后续续包仅按 index 路由，**不会**因为续包不再带 type 而退化处理。
- `_collect_output_items` 与 `_close_all_function_calls` 都更新为同时收集 function_call 与 custom_tool_call。

## Patch 4

### 设计说明

- `chat_to_responses.translate_response` 新增 `_gather_annotations` helper，与 `_gather_function_calls` / `_gather_refusal` / `_gather_reasoning_summary` 同级。
- `responses_to_chat.translate_response` 在构造 output_text part 时把 chat msg.annotations 直接列表拷贝过去（保持原 annotation dict 结构，不做格式判断；spec 与 chat 端 url_citation 等结构 1:1）。
- stream_r2c #35：chat SSE 协议没有 annotation 增量事件，本实现把 annotation 累积到 state.annotations，由 `get_downstream_chat_assistant()` 汇总到 message.annotations 供 failover fingerprint_write_chat 等下游用途使用。流式过程中**不**主动 yield annotation 事件给下游 chat。

## Patch 5

### 设计说明

- `RESPONSE_ERROR_CODES` 取自 `schemas_registry: ResponseError.code` enum 全部 18 个值；`_CHAT_TYPE_TO_RESP_CODE` 映射涵盖 OpenAI/Anthropic/常见上游的 error.type 主流命名。
- stream_c2r._emit_failed 的 error 字段从 `{message, type}` 改为 spec 正式的 `{message, code}`，符合 ResponseError 形状。
- #18 legacy delta.function_call：复用 _handle_tool_call_delta，固定 index=0，等价于把"老协议第一个函数调用"挂在 tool_calls[0]。
- #10 assistant 全空 skip：此修复仅作用于 `t == "message" and role == "assistant"` 直接走 message 分支的情况；走 pending_assistant 分支（带 tool_calls）的逻辑由 `_flush()` 自然处理（content=None 与 tool_calls 共存合法）。

## Patch 6

### 偏离 / 调整

1. **`test_openai_m3.py::test_c2r_translate_request_basics` 测试更新（必要）**
   - 原断言 `items[0]["role"] == "developer"`，对应原"system→developer 强制改名"行为。
   - Patch 6 / #22 修复后，system 保持原 role；测试改成断言 `"system"`。

### 设计说明

- 03-fix-plan 把 #44/#45/#46 SSE 多 data 行拼接列在 Patch 6，但生产中从未观察到。本 Patch 加了一个最低断言 (test_bug45_sse_multiple_data_lines_join) 验证不 raise；多 data 行的完整 SSE-spec 拼接（用 `\n` join）暂未实现，因为：
  - 生产 chat / responses 上游都只发一行 data
  - 改动会影响所有 SSE 解析路径，风险大于收益
  - 列入 05-implementation-diary.md 的 TODO，需要时再做
- #19（reasoning summary vs reasoning_text 区分）：当前实现把 summary 与 reasoning_text 都拼到 `reasoning_content`，下次回放全部当 summary。03 标 P2，影响仅限于"完整往返时 reasoning_text/summary 角色互换"。本 Patch 不动语义（保持 P0/P1 优先），列入 TODO。
- #36（_stringify_tool_content 严格化）：assistant array content 的拍扁路径用 `_stringify_tool_content`，行为基本正确（仅取 text）。本 Patch 不重写为专用函数，保持现状；将来若发现 assistant content 中混入非 text/refusal part 才需要重构。
- #38（reasoning 跨轮保留）：02 文档自己降级为低优；保持现状。
- #44/#46 SSE [DONE] 处理：responses 流通常不发 [DONE]，本代码 silently no-op，符合预期，不动。
- 附录小修：reasoning item 加 status:"completed"（已加）；GuardError 已支持 422（构造函数本身就接 status int，无需修改）。

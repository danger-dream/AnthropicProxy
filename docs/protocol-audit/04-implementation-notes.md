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

# 02 · 现有代码 Bug / 不完备清单

> 严重度：**P0** 致命（请求/响应整段失败、上游 400、协议不可解析） · **P1** 常见路径翻车 · **P2** 边界条件失误 · **P3** 兼容性 / 严格客户端校验问题  
> 文件路径全部相对 `/opt/src-space/anthropic-proxy/`。  
> 行号给的是当前 HEAD 的 `responses_to_chat.py`/`chat_to_responses.py`/`stream_r2c.py`/`stream_c2r.py`/`guard.py`/`common.py` 的实际行号。

---

## 编号索引

| # | 严重度 | 文件 | 函数 | 简述 |
|---|---|---|---|---|
| 1 | **P0** | responses_to_chat.py | `_input_items_to_messages` | 裸消息（无 `type:"message"`）被 `t == "message"` 分支拒收，整批 silently drop |
| 2 | **P0** | responses_to_chat.py | `_resolve_input` | `body["model"]` 必填字段未检查，缺失会 KeyError 而非返回 400 |
| 3 | **P1** | responses_to_chat.py | `_input_items_to_messages` | `function_call_output.output` 是 array 时直接当字符串扔给 chat tool message，会变成 `"[{...},{...}]"` |
| 4 | **P1** | responses_to_chat.py + chat_to_responses.py | `_content_*` | `input_image.file_id` 字段双向丢失 |
| 5 | **P2** | chat_to_responses.py | `_content_chat_to_responses` | `file` part 的 `file_url` 字段丢失；同时未透传 `detail` |
| 6 | **P1** | responses_to_chat.py | `_content_responses_to_chat` | 翻译出 `input_audio` part，但 spec 中 `InputContent` 没有 audio；这条分支是死代码（且若 chat 上游回的 message content 不含 input_audio 也无意义） |
| 7 | **P2** | stream_r2c.py | `_mk_error_chunk` / `_on_error` | 上游 error.code/param 没透传到 chat error 帧 |
| 8 | **P2** | stream_c2r.py | `_emit_failed` | response.failed 中 `error.code` 直接用上游 chat 的 error.type，未约束到 `ResponseErrorCode` 18 个 enum 值；非法值客户端反序列化失败 |
| 9 | **P0** | chat_to_responses.py / stream_c2r.py / responses_to_chat.py | `_usage_*_to_resps*` | `ResponseUsage` 的 `input_tokens_details.cached_tokens` 与 `output_tokens_details.reasoning_tokens` spec 标 *required*；当前仅在非 0 时写入，0 时整段 details 缺失，严格客户端反序列化失败 |
| 10 | **P1** | responses_to_chat.py | `_input_items_to_messages` (assistant 分支) | 当 assistant message content 同时为空（既无 text 也无 refusal）时 content=None，但若该 message 后续被 chat 上游严格校验"必须有 content 或 tool_calls"会 400 |
| 11 | **P1** | chat_to_responses.py / responses_to_chat.py | `translate_request` | `verbosity` ↔ `text.verbosity` 双向均未映射，全部丢失 |
| 12 | **P2** | responses_to_chat.py | `translate_request` | `reasoning.summary`（auto/concise/detailed）未映射 |
| 13 | **P1** | stream_c2r.py | `_response_skeleton` | response.created/in_progress 携带的 Response 对象缺很多 spec 必填字段（`tools`、`metadata`、`tool_choice`、`temperature`、`top_p`、`parallel_tool_calls`、`reasoning` 等）；严格客户端会拒 |
| 14 | **P1** | stream_c2r.py | `_emit_terminal` / `_collect_output_items` | reasoning item 中 `summary[].text` 用了拼出来的 buffer，但缺 `OutputMessage`、`ReasoningItem` 必填的 `status` 字段 ✅（reasoning 本代码漏；message 本代码已加） |
| 15 | **P0** | chat_to_responses.py | `_messages_to_input_items` | role=`function`（legacy）的消息走到 default 分支，被当 user/system 处理；spec 中 `function_call`+`name`+`tool_call_id` 不存在，应映射为 function_call_output 或 400 |
| 16 | **P1** | stream_c2r.py | `_emit_refusal_delta` / `_close_message_item` | `content_index` 假定 text 在 0、refusal 在 1；如果 refusal 先于 text 出现，refusal 用 0，text 后续再开就会要 1 但代码写死 0 |
| 17 | **P1** | stream_c2r.py | `_close_function_call` | `response.function_call_arguments.done` 缺 spec 必填 `name` 字段 |
| 18 | **P2** | stream_c2r.py | `_handle_choice` | 不处理 `delta.function_call`（legacy）；上游若用旧字段会丢调用 |
| 19 | **P2** | responses_to_chat.py / chat_to_responses.py | `_gather_reasoning_summary` / 反向 | 把 `summary` 与 `content`(reasoning_text) 两类文本无差别拼接到 `reasoning_content`；下次回放时全部当 summary，丢失了二者语义 |
| 20 | **P0** | stream_r2c.py | `_on_completed` | 不发任何 chat chunk，依赖 `close()` 收尾，但若上游不主动关流（连接中断、`response.completed` 后又有事件），可能漏发 finish_reason；同时 `terminal_emitted` 未在 completed 时 set，error 后也只有 close 才发 [DONE] |
| 21 | **P1** | guard.py | `guard_responses_to_chat` `_BUILTIN_TOOL_TYPES` | 缺：`web_search`（v2 名）、`computer`、`computer_use`、`web_search_preview_2025_03_11`、`apply_patch`、`function_shell`、`custom`、`web_search_2025_08_26`；当前代码会用"未知 type" 分支兜底拒绝，但错误信息不友好 |
| 22 | **P2** | chat_to_responses.py | `_messages_to_input_items` | system role 强制改为 `developer`；spec 里 `EasyInputMessage.role` 同时支持 system 和 developer，强制改名会让某些上游 instructions 优先级判断错（system > developer 的模型反而被弱化） |
| 23 | **P1** | chat_to_responses.py + responses_to_chat.py + guard.py | `_translate_tool_choice_*` | `tool_choice` 形态 `{type:custom,custom:{name}}`/`{type:custom,name}` 双向均未映射 |
| 24 | **P1** | chat_to_responses.py + responses_to_chat.py + guard.py | `_translate_tool_choice_*` | `tool_choice = {type:allowed_tools, allowed_tools|tools, mode}` 双向均未映射 |
| 25 | **P1** | guard.py | `guard_responses_to_chat` | 不拦 `tool_choice` 是 hosted/MCP/allowed_tools/custom/specific_apply_patch/specific_function_shell 时的请求；这些到 chat 上游会 400，但代理不预拦截 |
| 26 | **P1** | chat_to_responses.py | `_flatten_tool` | `CustomToolChatCompletions{type:custom,custom:{name,description?,format?}}` 不展开为 `{type:custom,name,description?,format?}`；当前代码 fallback 直接 `dict(t)`（仍带 `custom` 嵌套，responses 会 400） |
| 27 | **P1** | chat_to_responses.py + stream_c2r.py | `_messages_to_input_items` / `_handle_tool_call_delta` | assistant.tool_calls 中 type=custom 的 `ChatCompletionMessageCustomToolCall{custom:{name,input}}` 未翻译为 responses 端的 `CustomToolCall{name,input}`；当前代码当 function 处理，输出格式错 |
| 28 | **P2** | responses_to_chat.py | `translate_response` | `OutputTextContent.annotations[]` 在 chat 端有同名 `message.annotations[]`，但 R→C 未回填；C→R 反向也未读取 chat annotations |
| 29 | **P3** | stream_c2r.py | `_emit_output_text_delta`/`_close_message_item` | `response.output_text.delta`/`done` 的 `logprobs` 字段在 spec 是 *required*；当前不带 |
| 30 | **P1** | chat_to_responses.py | `_flatten_tool` | `FunctionTool.strict` 在 spec 标 *required*（responses 端）；上游不传 strict 时本代码不写，responses 上游会 400 |
| 31 | **P2** | stream_r2c.py | `_handle_event_block` | 未处理 `response.queued`（background 路径，本代理已剥 background，不是必须，但 guard 仅剥到 chat ingress 侧 background；R→C 路径若上游真发 queued 事件会被忽略而不是发 role/created） |
| 32 | **P3** | stream_r2c.py | `R2CState` | `chunk_id`、`created_ts` 与上游 `response.created.response.id`/`created_at` 完全无关；丢失链路追踪能力（轻微，但调试难） |
| 33 | **P2** | stream_r2c.py | `_on_output_item_added` | 仅为 `function_call` 处理；若上游连续 emit 多个 message item（极少见但 spec 允许），下游 chat 流的所有 text 会被合并到一个 message 里（丢段落） |
| 34 | **P3** | stream_c2r.py | `_emit_reasoning_text_delta` | `summary_index` 固定 0；spec 允许多个 summary_part；如果未来上游 chat reasoning_content 用换段表达多个 part，本代码无法表达 |
| 35 | **P2** | stream_r2c.py | `_handle_event_block` | 未处理 `response.output_text.annotation.added`；annotations 信息全部丢失 |
| 36 | **P1** | chat_to_responses.py | `_messages_to_input_items` | assistant 的 array content 直接用 `_stringify_tool_content` 拍扁成纯文本；但 `_stringify_tool_content` 既扫 type=text 也扫任何带 `text` key 的 dict，行为不严谨；assistant array content 只可能是 text/refusal，不应走 stringify |
| 37 | **P3** | chat_to_responses.py | `_messages_to_input_items` | tool/function_call_output 的 chat tool message `content` 在 spec 是 *required*；本代码 None 时变成 ""，OK；但 array 时 stringify 仅取 text，丢失 image/file annotation 标识（chat tool message 严格只允许 text，所以这里 OK；无 bug，留作记录） |
| 38 | **P1** | responses_to_chat.py | `_input_items_to_messages` | reasoning item 收集到的文本在跳过 user/system 时会清空；但 spec 允许 reasoning 出现在 `function_call_output` 之后 / 多 reasoning item 串联，应保留连续性 |
| 39 | **P3** | common.py | `CHAT_REQ_ALLOWED` | 不包含 `messages`、缺一些字段如 `function_call`/`functions` 都已加；但 `web_search_options` 在 chat 是合法的，passthrough 已包含 ✅；缺 `repetition_penalty` 等社区扩展字段（非 OpenAI 官方）—— 不处理 OK |
| 40 | **P2** | guard.py | `guard_chat_to_responses` | `prediction` 字段未拦截；它在 responses 没对应字段，drop 后客户端"以为"会做 prediction，实际无效（应至少 log warning） |
| 41 | **P1** | stream_c2r.py | `close()` | `terminal_emitted` 已 set，但 `_save_to_store_if_configured()` 只在非 error 路径调用；流被中途 `close()`（客户端断连）时 store 没有写入，失去续接能力 |
| 42 | **P2** | responses_to_chat.py | `translate_response` | `current_input_items` 在调用方拿"全部 input"还是"本次 input"取决于调用方；本代码注释明确要求是当前请求的 input_items（不含 prev 历史），但参数名容易误用（无类型检查） |
| 43 | **P2** | stream_r2c.py | `_on_completed` 流终止前流式 chunk usage 的处理 | 当 `include_usage=true` 时官方 chat 行为是 **每个 chunk 都带 usage:null**（最末 chunk 才带 usage）；本代码只在末帧带 usage，从未带 usage:null，部分 SDK 会困惑 |
| 44 | **P1** | stream_c2r.py | `_handle_choice` | 不处理 chat 上游 chunk 中的 `choices[0].delta.role` 后到的语义切换（例如上游先发 role 后才发 content）；本代码假定 first chunk 必然带 content/refusal/tool_calls；若上游分两个 chunk（chunk1 仅 role，chunk2 才 content）会让 `_ensure_created` 在 role chunk 时已发 created，但 message item 未开 → OK，但 `delta.role` 本身被丢弃，不影响 |
| 45 | **P2** | stream_c2r.py | `_handle_block` | 多个 `data:` 行同一 block 时只取最后一个（spec 实际上一个 SSE block 可以多 data 行被拼接成 \n 分隔的字符串） |
| 46 | **P3** | stream_r2c.py | `_parse_event_block` | 同上，`data: [DONE]` 的解析依赖 strip 后等于 `[DONE]` —— responses 流通常不发 DONE，但若发了，本代码 silently treat as no-op |

---

## P0 详细分析

### #1 — `_input_items_to_messages` 不识别裸消息

**文件**：`src/openai/transform/responses_to_chat.py`，`_input_items_to_messages`（约 142~218 行）

**问题描述**：spec 中 `InputItem = oneOf [EasyInputMessage, Item, ItemReferenceParam]`，其中 `EasyInputMessage` 的 `type` 字段是 `optional`（const="message"）。也就是说：
```json
{"role": "user", "content": "hi"}   // 完全合法的 InputItem
{"role": "user", "content": [{"type":"input_text","text":"hi"}]}   // 同上
```

guard 已经放行（不拦无 type 的 item），但 translate 层 `t = item.get("type")` 拿到 `None`，所有 if/elif 都不命中，被 silently skip → `messages: []` → chat 上游 400 `messages: must contain at least one message`。

**触发条件**：客户端按 EasyInputMessage 直接构造 input（OpenAI Python SDK 在 `client.responses.create(input=[{"role":"user","content":"hi"}])` 时即如此）。

**修复（伪代码）**：
```python
for item in items:
    if not isinstance(item, dict):
        continue
    t = item.get("type")
    role = item.get("role")
    # 裸消息：无 type 字段但有 role → 视为 message
    if t is None and role in ("user", "assistant", "system", "developer"):
        t = "message"
    if t == "message":
        ...
```

更进一步，建议引入一个白名单 `_KNOWN_ITEM_TYPES`，未知 type 走 fallback：
```python
if t is None:
    t = "message" if role else None
```

---

### #2 — `_resolve_input` / `translate_request` 不校验 model

**文件**：`responses_to_chat.py:30~50, 79`

`payload = {"model": body["model"], ...}` 直接 dict 取键；缺失会 KeyError 透出 500。  
**修复**：guard.guard_responses_ingress 内补一个 `if not body.get("model"): _fail(400, ..., "missing model")`。chat 同侧已隐含通过 chat passthrough，但跨变体 chat→responses 也存在同问题（`chat_to_responses.py:36`）。

---

### #9 — Usage details 必填字段缺失

**文件**：`chat_to_responses.py:_usage_resps_to_chat`（行尾段）；`responses_to_chat.py:_usage_chat_to_resps`；`stream_c2r.py:_usage_chat_to_resps_stream`；`stream_r2c.py:_usage_resps_to_chat_stream`。

**spec**（ResponseUsage）：
```yaml
required:
  - input_tokens
  - input_tokens_details   # required
  - output_tokens
  - output_tokens_details  # required
  - total_tokens
input_tokens_details:
  required: [cached_tokens]
output_tokens_details:
  required: [reasoning_tokens]
```

**当前代码**（4 处一致）：
```python
if cached:
    res["input_tokens_details"] = {"cached_tokens": cached}
if reasoning:
    res["output_tokens_details"] = {"reasoning_tokens": reasoning}
```

**触发**：cache 为 0、未推理的请求。
**修复**：始终写入：
```python
res["input_tokens_details"] = {"cached_tokens": cached}
res["output_tokens_details"] = {"reasoning_tokens": reasoning}
```

---

### #15 — role=function legacy 消息未处理

**文件**：`chat_to_responses.py:_messages_to_input_items`（约 80~140 行）

**spec**：`ChatCompletionRequestFunctionMessage` 必填 `role:"function", content, name`，是 deprecated 的旧 function calling 协议。

**当前代码**：
```python
if role == "tool": ...
if role == "assistant": ...
# 否则
mapped_role = role or "user"
if mapped_role == "system":
    mapped_role = "developer"
items.append({"type":"message","role":mapped_role,"content":...})
```

`role="function"` 落入最后分支，被翻译成 `{type:message, role:"function", content:...}` —— responses 不认 `function` role（仅允许 user/system/developer/assistant），上游 400。

**修复**：
```python
if role == "function":
    # 老协议：function 消息 → function_call_output
    items.append({
        "type":"function_call_output",
        "call_id": msg.get("name") or "",   # 旧协议没有 call_id，用 name 兜底
        "output": _stringify_tool_content(msg.get("content")),
    })
    continue
```
或在 `guard.guard_chat_to_responses` 中预拒绝 role=function。

---

### #20 — stream_r2c 收尾依赖 close 但未自我兜底

**文件**：`stream_r2c.py:_on_completed/_on_incomplete`

`_on_completed` 把 finish_reason 暂存到 state 后什么都不发，全部留给 `close()`。如果上游不主动关流（HTTP 断连），调用方的 `close()` 仍会被调，问题不大；但代码注释里 `terminal_emitted` 仅在 close() 中 set，**`_on_completed` 之后又收到上游事件（通常不会发生但合规模型可能在 completed 后再发 done 事件）会被处理为正常事件**，破坏状态。

**修复**：在 `_on_completed`/`_on_incomplete` 之后立即 set `state.terminal_status` 并 return；后续事件直接忽略（可加 `if self.state.terminal_status: return`）。

---

## P1 详细分析（节选）

### #3 — `function_call_output.output` 是 array 时未拍扁

**文件**：`responses_to_chat.py:_input_items_to_messages` 中 `t == "function_call_output"` 分支：
```python
messages.append({
    "role": "tool",
    "tool_call_id": item.get("call_id") or "",
    "content": item.get("output") or "",
})
```

**spec**（`FunctionCallOutputItemParam`）：`output` 是 `oneOf {string, array<{InputTextContent|InputImageContent|InputFileContent}>}`。array 时直接放进 `chat.tool.content` 会变成 `[{"type":"input_text","text":"..."},...]` —— chat 端 tool message 的 content 只允许 `string` 或 `array<{type:text}>`，input_text/input_image 上游会 400。

**修复**：增加分支
```python
output = item.get("output")
if isinstance(output, list):
    parts = []
    for p in output:
        if isinstance(p, dict) and p.get("type") in ("input_text","output_text","text"):
            parts.append(p.get("text",""))
    output = "".join(parts)
elif not isinstance(output, str):
    output = ""
```

---

### #4 — `image_url.file_id` 双向丢失

**文件**：`chat_to_responses.py:_content_chat_to_responses`（已读 `iu.get("file_id")`）✅；`responses_to_chat.py:_content_responses_to_chat` ❌（仅读 `image_url`/`detail`）。

**spec**（`InputImageContent`）：`image_url, file_id, detail` 三选一 image_url 或 file_id。  
**修复**：r→c 时若有 file_id，输出 `{type:image_url, image_url:{url:"", file_id:p["file_id"], detail:...}}`；chat 上游普遍不识别但至少不丢失。或 raise warning。

---

### #6 — input_audio 在 R→C 是死代码

**文件**：`responses_to_chat.py:_content_responses_to_chat`：
```python
elif pt == "input_audio":
    out.append({"type":"input_audio", ...})
```

**spec**：Responses 的 `InputContent` = oneOf {input_text, input_image, input_file}，**不包含 input_audio**。  
所以这个分支永远不会命中（除非客户端违规发 input_audio 进 responses ingress —— guard 应拒）。

**修复**：删除该分支；或在 guard.guard_responses_ingress 显式拒绝 content 含 input_audio。

---

### #7 — chat error 帧丢 code/param

**文件**：`stream_r2c.py:_mk_error_chunk`：
```python
obj = {"error":{"message": message, "type": "server_error", "code": None, "param": None}}
```

`_on_error` 拿到 `data["code"]/data["param"]` 但只读 message。OpenAI 客户端（python SDK）会用 code 做分支处理。  
**修复**：把 `err_body.get("code")` / `err_body.get("param")` / `err_body.get("type")` 透传。

---

### #8 — response.failed.error.code 不在 enum

**文件**：`stream_c2r.py:_emit_failed`：
```python
"error": {"message": ..., "type": err.get("type") or "server_error"},
```

**spec**：`ResponseError.code` enum 只有 18 个：`server_error, rate_limit_exceeded, invalid_prompt, vector_store_timeout, invalid_image, ...`。chat 上游的 `error.type` 是 `invalid_request_error`/`api_error` 等完全不同 enum。  
**修复**：
1. 取 `err.get("code")`（如果上游有），否则映射 `err.get("type")` → `ResponseErrorCode`：`rate_limit_error→rate_limit_exceeded`、其它→`server_error`。
2. 字段名应该是 `code` 不是 `type`（spec 里是 `code`+`message`，没有 `type`）。

---

### #10 — assistant message 空 content + 空 refusal 时 content=None

**文件**：`responses_to_chat.py:_input_items_to_messages`（assistant 分支）：
```python
msg_out = {
    "role": role,
    "content": (_content_responses_to_chat(non_refusal_parts)
                if non_refusal_parts else None),
}
```

**spec**：`ChatCompletionRequestAssistantMessage.content` 是 `nullable`，但仅当 `tool_calls` 或 `function_call` 存在时可为 null。如果该 assistant message 既无 content 也无 tool_calls 也无 refusal（不应出现，但 responses output 里若 model 真的产出了空 message，本代码会 emit 空 assistant message）→ 上游 400。

**修复**：assistant 完全空时 skip 该 message（不 append），或 content="" 占位。当前 `_flush()` 处理 pending_assistant 时也没处理这个边界 —— pending_assistant 默认 content=None，刚好对得上 tool_calls 必存在的语义，OK；但 message 分支是另一个路径，需补防御。

---

### #11 — verbosity 双向未映射

`chat.verbosity`（CreateChatCompletionRequest）↔ `responses.text.verbosity`（ResponseTextParam）—— 两个 enum 完全相同（`low/medium/high`），但翻译层根本没读这个字段。

**修复**：
- C→R：`if "verbosity" in body: payload.setdefault("text",{})["verbosity"] = body["verbosity"]`
- R→C：`text.verbosity` 提取时单独 `payload["verbosity"] = text_cfg["verbosity"]`

---

### #13 — Response skeleton 不全

**文件**：`stream_c2r.py:_response_skeleton` 只塞 9 个字段，但 `Response` spec 标 *required* 共 14 个：`id, object, created_at, error, incomplete_details, instructions, model, tools, output, parallel_tool_calls, metadata, tool_choice, temperature, top_p`。

缺失：`tools`、`parallel_tool_calls`、`metadata`、`tool_choice`、`temperature`、`top_p`、`reasoning`、`text`、`truncation`、`status` 等。

**修复**：从 ingress body 把这些字段传进 StreamTranslator 构造器，skeleton 时回填默认值（`tools=[]`、`parallel_tool_calls=true`、`metadata={}`、`tool_choice="auto"`、`temperature=1`、`top_p=1`、`reasoning={"effort":null,"summary":null}`、`text={"format":{"type":"text"}}`、`truncation="disabled"`）。

---

### #14 — output items 缺 status / 必填字段

`stream_c2r._collect_output_items` 给 message 加了 `status:"completed"` ✅；但 `ReasoningItem` spec required: `id, summary, type` —— OK；缺的是 `status`（spec 里 status 不在 required，但是 spec 鼓励 populated；某些客户端会校验）。

`function_call` item: `_close_function_call` 输出 `status:"completed"` ✅。

主要问题在：`response.completed/incomplete/failed` 中的 `Response.output[]` 与上面 _emit_terminal 里复制的 items 应一致 —— 当前 `_emit_terminal` 在 `_emit_terminal()` 之前已 `_close_text_item` + `_close_all_function_calls`，所以 closed_items 完整 ✅。但 `_emit_failed` 也复制了一份 `_collect_output_items`，未 sync `closed_items`，可能漏 message_item / reasoning_item 中的"已 emit 但未关"的 part —— 检查代码发现 `_emit_failed` 里先调 `_close_text_item`/`_close_all_function_calls`，OK ✅。

---

### #16 — refusal content_index 写死

```python
def _emit_refusal_delta(self, text):
    idx = 1 if item.content_part_opened else 0
```

`content_part_opened` 只反映 text part；多 refusal-only 流会 OK，但 text + refusal 混杂时需保证 refusal 在 text 之后；如果上游先 refusal 后 text（unlikely 但 spec 允许），text 会被开为 0，refusal 后续要 1，但 text 此时 idx 计算是 0（OK），refusal 已经是 0（撞）。

**修复**：在 `_MessageItem` 加 `_next_content_index: int = 0`，每开一个 part `++`。

---

### #17 — function_call_arguments.done 缺 name

`stream_c2r._close_function_call`：
```python
yield _emit("response.function_call_arguments.done", {
    "type": ..., "item_id": fc.fc_id, "output_index": fc.output_index,
    "arguments": fc.args_buf,
    # 缺 name！
    "sequence_number": ...,
})
```

spec required: `type, item_id, name, output_index, arguments, sequence_number`。  
**修复**：补 `"name": fc.name`。

---

### #21 — built-in tool 白名单不全

`guard._BUILTIN_TOOL_TYPES` 缺：
- `web_search`（v2）
- `web_search_2025_08_26`
- `web_search_preview_2025_03_11`
- `computer`
- `computer_use`
- `apply_patch`
- `function_shell`
- `custom`（虽然是 user-defined，但 chat 端结构不同）

当前的 `if ttype not in _BUILTIN_TOOL_TYPES` 兜底分支会拒绝未知 type（包含 web_search v2），错误信息是 "unsupported tool type"，看起来像 bug 报告而不是预期拒绝。建议补全名单 + 给出友好错误：

```python
_BUILTIN_TOOL_TYPES |= {"web_search","web_search_2025_08_26",
                        "web_search_preview_2025_03_11",
                        "computer","computer_use",
                        "apply_patch","function_shell"}
```

---

### #23 / #24 — tool_choice 形态遗漏

spec `ToolChoiceParam` = oneOf 8 形态，本代码只识别 `string` 和 `{type:function,...}`：

| 形态 | spec | 当前 |
|---|---|---|
| string | ✅ | ✅ |
| function | ✅ | ✅ |
| custom | `{type:custom, name}` ↔ `{type:custom, custom:{name}}` | ❌ 透传原 dict，名字层级错 |
| allowed_tools | `{type:allowed_tools, mode, tools[]}` ↔ `{type:allowed_tools, allowed_tools:{mode,tools[]}}` | ❌ |
| hosted (file_search/web_search_preview/computer/...) | `{type: <hosted>}` | ❌（C→R 不需要；R→C guard 应拒） |
| MCP | `{type:mcp, server_label, name?}` | ❌ |
| ApplyPatch / FunctionShell specific | spec 各异 | ❌ |

**修复**：
- C→R `_translate_tool_choice_c2r`：custom 形态 `{"type":"custom","custom":{"name":x}}` → `{"type":"custom","name":x}`；allowed_tools 类似。
- R→C `_translate_tool_choice_r2c`：反向。
- `guard.guard_responses_to_chat`：tool_choice.type ∈ {hosted,mcp,allowed_tools,custom,specific_apply_patch,specific_function_shell} 时 400。

---

### #26 — chat custom tool 不展开

`chat_to_responses._flatten_tool` 只处理 type=function；type=custom 走 fallback `dict(t)`，结果 `{type:custom, custom:{name,...}}` 直接到 responses 上游，但 responses 端 `CustomTool` 是 `{type:custom, name, description?, format?}` —— 字段层级不一致 → 400。

**修复**：
```python
if t.get("type") == "custom":
    c = t.get("custom") or {}
    out = {"type":"custom"}
    for k in ("name","description","format"):
        if k in c: out[k] = c[k]
    return out
```

---

### #27 — assistant.tool_calls type=custom 不翻译

类似 #26 + chat stream 中的 `delta.tool_calls[i]` 也没 custom 分支。  
**修复**：在 `_messages_to_input_items` assistant 分支中针对 `type=="custom"`：
```python
items.append({
    "type":"custom_tool_call",
    "call_id": tc.get("id") or _gen_id("call_"),
    "name": (tc.get("custom") or {}).get("name",""),
    "input": (tc.get("custom") or {}).get("input",""),
})
```
stream_c2r 同理；c2r 流式还要新增 `_CustomToolCallItem` 状态机 + emit `response.custom_tool_call_input.delta/done`。

---

### #30 — FunctionTool.strict 必填未补默认

spec `FunctionTool` required: `[type, name, strict, parameters]`。chat 上游不传时本代码 _flatten_tool 不写 `strict` 字段，responses 上游 schema 校验失败。  
**修复**：`out.setdefault("strict", False)` 与 `out.setdefault("parameters", {})`。

---

### #41 — 流式断连时 store 不写

`close()` 在 `terminal_error` 时 return，**不调用 `_save_to_store_if_configured`**。客户端中途断连、上游 502 时（已经发了 message item 但没 completed），下游断流 → `feed` 检测到 io 异常 → 调 close → 跳过 store。下次 client 用 `previous_response_id` 续接 → 404 → 客户端无法重试。

**修复**：在 `_emit_failed` 之后也尝试 `_save_to_store_if_configured`，但加个 flag `parent_id` 仍记录 `status:"failed"` 以便区分。

---

### #43 — include_usage=true 时中间 chunk 不带 usage:null

OpenAI 文档明确：`stream_options.include_usage=true` 时**所有 chunk 都带 `usage` 字段**，中间 chunk 是 `null`，最后 chunk 才是真值。当前 `stream_r2c._mk_chunk` 只在 close() 末帧带 usage，中间不带；某些 SDK（如 LangChain）会做 `chunk.usage` 存在性判断而困惑。

**修复**：`_mk_chunk` 在 `include_usage=true` 时给 obj 设 `usage: null`。

---

## P2 / P3 详细分析

由于篇幅，以下精简罗列触发与修复：

### #5 file_url / detail 丢失
file part：spec `InputFileContent` 多了 `file_url, detail`；chat→responses 不读这两；responses→chat 不写。**修复**：双向补齐。

### #12 reasoning.summary 丢失
`reasoning.summary` enum {auto,concise,detailed} 是上游能力的指示；R→C 时 chat 没有对应字段，drop OK；但 C→R 时若客户端透传 chat 端非官方 `reasoning_summary` 字段（DeepSeek 生态有）应映射（按需）。

### #18 delta.function_call legacy
chat stream 中 `delta.function_call` 在某些代理（如 LiteLLM 旧版）会出现；stream_c2r 当前不处理。**修复**：把 legacy function_call 视作 tool_calls[0] 同等处理。

### #19 reasoning summary vs reasoning_text 混合
`_gather_reasoning_summary` 把 summary 与 reasoning_text 合并到同一 `reasoning_content`。下次 chat→responses 全部当 summary，content 字段为空。
**修复**：要么用 marker 分段，要么在 chat 端用两个字段（`reasoning_content` + `reasoning_text` 非官方）。

### #22 system → developer 强制改名
`mapped_role = "developer"` 对所有 system role 一刀切。spec EasyInputMessage 同时支持 system 和 developer，应保留原 role。**修复**：去掉强制改名（改完后 ingress 守住即可）。

### #25 tool_choice 不预拦
见 #23 修复。

### #28 annotations 未回填
chat ResponseMessage.annotations[] 与 responses output_text.annotations[] 是 1:1 映射（同 url_citation 结构），双向都没读。**修复**：r→c 时拼到 chat assistant.annotations；c→r 时（output_text part）写入 annotations。

### #29 logprobs 必填
spec output_text.delta/done.logprobs 必填。**修复**：始终写 `logprobs: []`。

### #31 response.queued 忽略
低优；本代理已剥 background。

### #32 chunk_id / created_ts 与上游脱钩
建议在 `R2CState` 中保存 `upstream_response_id`，从 `response.created` 中提取，方便日志关联。

### #33 多 message item 合并
**触发**：上游 splitter 模型把 reasoning 分两段、message 分两段。**修复**：每次 output_item.added(message) 都新开一段，emit 一个 `delta:{role:assistant}` chunk + 后续 content 累加。

### #34 summary_index 写死 0
未来扩展；当前 chat 端只有一个 reasoning_content 字段，OK。

### #35 annotations 流事件忽略
`response.output_text.annotation.added` 应映射为 chat `delta:{}` + 把 annotation 累积，最后 close 时塞 `message.annotations`（chat stream 中 annotation 没法增量，只能在 message 完成时 close 帧带；但 chat stream 协议本身没"annotation done"事件，只能丢失或非官方 emit）。

### #36 _stringify_tool_content 太宽松
扫所有带 `text` key 的 dict。对 assistant content 应严格 oneOf {text,refusal}，单独拆函数。

### #37 chat tool message 容忍 content array text-only
非问题。

### #38 reasoning 跨轮丢失
**触发**：history 里 assistant1 → tool_call → tool_response → reasoning → assistant2，期间 user message 不存在。当前在 `t == "message" and role != "assistant"` 时清空 pending_reasoning。tool 输出走 `t == "function_call_output"`（独立分支），不清空 pending_reasoning ✅。但 _flush() 在 function_call_output 分支被调用（关 pending_assistant），其中 `bridge` 的 reasoning 会被 setdefault 到上一条 assistant —— 实际行为符合预期 ✅。本条降级为低优。

### #40 prediction 不拦
**修复**：guard.guard_chat_to_responses 中 `if body.get("prediction"): log.warning(...)`，非阻断。

### #44 / #45 / #46 SSE 解析
chat SSE 严格只有一行 data；本代码循环读取最后一行，rare case 多 data 行丢失。生产中不曾观察到，但合规处理是用 `\n`.join。

---

## 跨函数对齐表

下面列出"guard 接 + translate 漏接"或"translate 接 + guard 漏拒"的对齐断裂：

| 输入条件 | guard | translate | 状态 |
|---|---|---|---|
| input 含 `{role:"user", content:"..."}`（裸） | 放行 | 漏接（#1） | **断裂 P0** |
| input 含 `{type:"function_call_output", output:[...]}` | 放行 | 漏接 array（#3） | **断裂 P1** |
| message 含 `role:"function"` 老协议 | 放行 | 漏接（#15） | **断裂 P0** |
| tools 含 `type:"custom"` | 放行 | 错位翻译（#26） | **断裂 P1** |
| assistant.tool_calls 含 `type:"custom"` | 放行 | 错位翻译（#27） | **断裂 P1** |
| tool_choice = `{type:"allowed_tools",...}` | 放行 | 透传字段层级错（#24） | **断裂 P1** |
| tool_choice = `{type:"custom",...}` | 放行 | 同上（#23） | **断裂 P1** |
| tool_choice = `{type:"file_search"}` 等 hosted | 放行 | 透传到 chat 上游 → 400（#25） | **断裂 P1** |
| message.content 包含 `input_audio` part | 拒绝（chat→resp） | n/a | OK |
| message.content 含未知 part type | 不拦 | 静默丢弃 | 一致（OK） |
| input 含 `web_search_call` 等 built-in items | 拒绝 | 防御 skip | OK |

---

完。下一份：`03-fix-plan.md`。

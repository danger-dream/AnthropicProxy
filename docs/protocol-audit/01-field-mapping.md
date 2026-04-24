# 01 · 协议字段映射表（Chat Completions ⇄ Responses）

> 引用基准：OpenAI OpenAPI spec v2.3.0（stainless 自动生成）  
> Schema 注册表：`/tmp/openai-docs/schemas_registry.json`  
> 适用代码：`src/openai/transform/{responses_to_chat, chat_to_responses, stream_r2c, stream_c2r, guard, common}.py`

文档约定：
- C→R = chat ingress ⇒ responses 上游；R→C = responses ingress ⇒ chat 上游。
- “是否透传”指 `common.filter_*_passthrough` 白名单包含与否。
- `(spec)` 列引用根 schema；如需展开，在 `schemas_registry.json` 中按名查。

---

## 1. 请求顶层字段

### 1.1 Chat 请求顶层（`CreateChatCompletionRequest`）

字段集合 = `CreateModelResponseProperties`（含 `ModelResponseProperties`）∪ object 内 props。共 35 个：

| Chat 字段 | 类型/约束（spec） | C→R 翻译策略 | 透传白名单 |
|---|---|---|---|
| `model` *required* | string | 直接拷到 `responses.model` | ✅ |
| `messages` *required* | array<`ChatCompletionRequestMessage`> | `_messages_to_input_items` 转 `input` | ✅（同协议） |
| `stream` | boolean | 直接拷 | ✅ |
| `stream_options` | `ChatCompletionStreamOptions{include_usage,include_obfuscation}` | `include_usage` 在 responses 不存在（usage 永远进 `response.completed`），整体丢弃 | ✅（同协议） |
| `temperature` | number 0~2 | 直接拷 | ✅ |
| `top_p` | number 0~1 | 直接拷 | ✅ |
| `n` | integer | guard 拦截 `n>1` | ✅ |
| `max_completion_tokens` | integer | → `responses.max_output_tokens` | ✅ |
| `max_tokens` (deprecated) | integer | 仅当 `max_completion_tokens` 缺失时 → `max_output_tokens` | ✅ |
| `stop` | string\|array<string>\|null | **无对应**，C→R drop（responses 不支持） | ✅（同协议） |
| `frequency_penalty` | number -2~2 | **无对应**，drop | ✅ |
| `presence_penalty` | number -2~2 | **无对应**，drop | ✅ |
| `logprobs` | boolean | guard 拒绝（C→R） | ✅ |
| `top_logprobs` | integer 0~20 | guard 拒绝（C→R） | ✅ |
| `logit_bias` | map<token,bias> | **无对应**，drop | ✅ |
| `tools` | array<`ChatCompletionTool`\|`CustomToolChatCompletions`> | `_flatten_tool` 扁平化 function；**custom 没翻译**（bug，见 02-#26） | ✅ |
| `tool_choice` | `ChatCompletionToolChoiceOption`（4 形态） | `_translate_tool_choice_c2r`：string 透传；`{type:function,function:{name}}`→`{type:function,name}`；其它形态未翻译（bug，见 02-#23、02-#24） | ✅ |
| `parallel_tool_calls` | boolean | 直接拷 | ✅ |
| `functions` (deprecated) | array | **不翻译**（注释明确说不接 legacy） | ✅（passthrough） |
| `function_call` (deprecated) | string\|object | **不翻译** | ✅（passthrough） |
| `response_format` | oneOf{text\|json_object\|json_schema} | → `text.format`（同构） | ✅ |
| `modalities` | array{text,audio} | guard 拒绝 audio；text 模态 drop | ✅ |
| `audio` | object{voice,format,...} | **无对应**，drop（guard 已拦 audio modality） | ✅ |
| `store` | boolean | 直接拷 | ✅ |
| `metadata` | map<str,str> | 直接拷 | ✅ |
| `seed` | integer | **无对应**，drop | ✅ |
| `prediction` | `PredictionContent` | **无对应**，drop | ✅ |
| `reasoning_effort` | enum{none,minimal,low,medium,high,xhigh} | → `reasoning.effort` | ✅ |
| `verbosity` | enum{low,medium,high} | **未实现**，应 → `text.verbosity`（bug 02-#11） | ✅ |
| `web_search_options` | object | **无对应**，drop（responses 通过 tools/web_search） | ✅ |
| `service_tier` | enum{auto,default,flex,scale,priority} | 直接拷 | ✅ |
| `user` (deprecated) | string | 直接拷 | ✅ |
| `safety_identifier` | string | 直接拷 | ✅ |
| `prompt_cache_key` | string | 直接拷 | ✅ |
| `prompt_cache_retention` | string | 直接拷 | ✅ |

> 注：`top_logprobs` 同时出现在 ModelResponseProperties 和 chat 顶层 schema 内（重复定义），实际只读一次。

### 1.2 Responses 请求顶层（`CreateResponse`）

字段集合 = `CreateModelResponseProperties` ∪ `ResponseProperties` ∪ object 内 props。共 29 个：

| Responses 字段 | 类型/约束（spec） | R→C 翻译策略 | 透传白名单 |
|---|---|---|---|
| `model` *required* | `ModelIdsResponses` (string) | 直接拷到 `chat.model` | ✅ |
| `input` | string \| array<`InputItem`> | `_resolve_input` + `_input_items_to_messages` 转 `messages` | ✅ |
| `include` | array<`IncludeEnum`>\|null | guard 静默剥除 `reasoning.encrypted_content`；其它项 **无对应**，drop | ✅ |
| `instructions` | string | 插入首条 system message | ✅ |
| `previous_response_id` | string | 走 store 展开历史，前置到 messages | ✅ |
| `conversation` | object | guard 拒绝（首版未支持） | ✅ |
| `context_management` | object | **无对应**，drop | ✅ |
| `stream` | boolean | 直接拷 | ✅ |
| `stream_options` | `ResponseStreamOptions{include_obfuscation}` | **无对应**，drop（chat 端通过 `stream_options.include_usage` 控制）| ✅ |
| `parallel_tool_calls` | boolean | 直接拷 | ✅ |
| `max_output_tokens` | integer\|null | → `chat.max_completion_tokens` | ✅ |
| `max_tool_calls` | integer\|null | **无对应**，drop（chat 不限制） | ✅ |
| `tools` | array<`Tool`>（function/built-in） | guard 拒绝非 function；function tool `_nest_tool` 嵌套 | ✅ |
| `tool_choice` | `ToolChoiceParam`（8 形态） | `_translate_tool_choice_r2c`：string 透传；`{type:function,name}`→`{type:function,function:{name}}`；其它未翻译（bug 02-#23、24） | ✅ |
| `text` | `ResponseTextParam{format,verbosity}` | `format` → `chat.response_format`；`verbosity` **未映射**（bug 02-#11） | ✅ |
| `reasoning` | `Reasoning{effort,summary,generate_summary}` | `effort` → `chat.reasoning_effort`；`summary` 未映射 | ✅ |
| `truncation` | enum{auto,disabled} | **无对应**，drop | ✅ |
| `background` | boolean | guard 静默剥除（代理无状态） | ✅ |
| `store` | boolean | 直接拷 | ✅ |
| `metadata` | map<str,str> | 直接拷 | ✅ |
| `prompt` | object | **无对应**，drop（无对应 chat 字段） | ✅ |
| `temperature` | number | 直接拷 | ✅ |
| `top_p` | number | 直接拷 | ✅ |
| `top_logprobs` | integer 0~20 | **无对应**（chat 有同名字段但语义略不同），drop；R→C 不映射 | ✅ |
| `service_tier` | enum | 直接拷 | ✅ |
| `user` (deprecated) | string | 直接拷 | ✅ |
| `safety_identifier` | string | 直接拷 | ✅ |
| `prompt_cache_key` | string | 直接拷 | ✅ |
| `prompt_cache_retention` | string | 直接拷 | ✅ |

> 一个语义差异：spec 明确规定 `previous_response_id` 与 `conversation` 互斥；本代码已分别处理。

---

## 2. 响应顶层字段

### 2.1 Chat 响应（`CreateChatCompletionResponse`）

| Chat 字段 | 类型/约束 | C→R 翻译（chat 上游 → responses 下游） |
|---|---|---|
| `id` *required* | string `chatcmpl-...` | 生成新 `resp_<uuid>` |
| `object` *required* | const `chat.completion` | const `response` |
| `created` *required* | integer (unix s) | → `created_at` |
| `model` *required* | string | 直接拷 |
| `choices[]` *required* | array{index,message,finish_reason,logprobs} | 拆 `message` 中各字段为 output items |
| `choices[].finish_reason` | enum{stop,length,tool_calls,content_filter,function_call} | `_finish_reason_to_status` 映射到 `status`+`incomplete_details` |
| `choices[].message.content` | string\|null | → `output_text` content part |
| `choices[].message.refusal` | string\|null | → `refusal` content part（独立 message item） |
| `choices[].message.tool_calls[]` | array<`ChatCompletionMessageToolCall`\|`ChatCompletionMessageCustomToolCall`> | function → `function_call` item；**custom 不翻译**（bug 02-#27） |
| `choices[].message.annotations[]` | array<url_citation> | **无对应**，drop（bug 02-#28） |
| `choices[].message.function_call` (legacy) | object | **不翻译** |
| `choices[].logprobs` | object\|null | **无对应**，drop |
| `service_tier` | enum | drop |
| `system_fingerprint` | string (deprecated) | drop |
| `usage` | `CompletionUsage` | `_usage_chat_to_resps` 映射 |

### 2.2 Responses 响应（`Response`）

`Response` 必填：`id, object, created_at, error, incomplete_details, instructions, model, tools, output, parallel_tool_calls, metadata, tool_choice, temperature, top_p`。

| Responses 字段 | 类型 | R→C 翻译策略 |
|---|---|---|
| `id` | string `resp_...` | → `chat.id`（前缀替换为 `chatcmpl-`） |
| `object` | const `response` | const `chat.completion` |
| `created_at` | number (unix s) | → `created` |
| `status` | enum{completed,failed,in_progress,cancelled,queued,incomplete} | `_status_to_finish_reason` |
| `error` | `ResponseError\|null` | `failed` 状态时 → 上层 raise/error 帧 |
| `incomplete_details.reason` | enum{max_output_tokens,content_filter} | → finish_reason `length`/`content_filter` |
| `model` | string | 直接拷 |
| `instructions` | string | drop（chat 不能携带） |
| `output[]` | array<`OutputItem`> | 聚合到 `choices[0].message` |
| `output_text` | string | 备用 fallback；优先用 output items |
| `usage` | `ResponseUsage` | `_usage_resps_to_chat` |
| `metadata` | map | drop |
| `parallel_tool_calls` | boolean | drop |
| `temperature/top_p/tool_choice/tools/text/reasoning/truncation/conversation/max_output_tokens/previous_response_id` | (回声字段) | drop |
| `completed_at` | number\|null | drop |

---

## 3. messages（Chat） ↔ input items（Responses） 结构

### 3.1 Chat message roles（`ChatCompletionRequestMessage` discriminator=role）

| role | content 形态 | 其它字段 | C→R 转换 |
|---|---|---|---|
| `system` | string \| array<TextPart> | `name?` | → `EasyInputMessage{type:message, role:developer, content}`（注：本代码强制改 developer，详见 02-#22） |
| `developer` | string \| array<TextPart> | `name?` | → `EasyInputMessage{type:message, role:developer}` |
| `user` | string \| array<UserPart> | `name?` | → `EasyInputMessage{type:message, role:user}` |
| `assistant` | string \| array<TextPart\|RefusalPart> \| null | `refusal?, audio?, tool_calls?, function_call?, name?` | 拆：`message` item（content）+ `function_call` items（每个 tool_call）+ refusal 单独 message item |
| `tool` | string \| array<TextPart> | `tool_call_id` *required* | → `function_call_output{call_id, output:string}` |
| `function` (deprecated) | string\|null | `name` *required* | **当前代码未处理**（fallthrough 到 user/system 默认分支）（bug 02-#15） |

### 3.2 Responses input item types（`InputItem` = oneOf [`EasyInputMessage`, `Item`, `ItemReferenceParam`]）

`Item` 的 oneOf：`InputMessage`, `OutputMessage`, `FileSearchToolCall`, `ComputerToolCall`, `ComputerCallOutputItemParam`, `WebSearchToolCall`, `FunctionToolCall`, `FunctionCallOutputItemParam`, `ToolSearchCallItemParam`, `ToolSearchOutputItemParam`, `ReasoningItem`, `CompactionSummaryItemParam`, `ImageGenToolCall`, `CodeInterpreterToolCall`, `LocalShellToolCall`, `LocalShellToolCallOutput`, `FunctionShellCallItemParam`, `FunctionShellCallOutputItemParam`, `ApplyPatchToolCallItemParam`, `ApplyPatchToolCallOutputItemParam`, `MCPListTools`, `MCPApprovalRequest`, `MCPApprovalResponse`, `MCPToolCall`, `CustomToolCall`, `CustomToolCallOutputResource`。

| Responses item.type | 必填 | R→C 转换 | 备注 |
|---|---|---|---|
| `message` (input/output) | `role,content` | role∈{user,system,developer}→ chat 同名 role；developer→system；assistant→ chat assistant message | refusal part 提取到 `message.refusal` |
| `function_call` | `call_id,name,arguments,type` | 聚合到上一条 assistant 的 `tool_calls[]` | id/call_id 区分见下表 |
| `function_call_output` | `call_id,type,output` | → `tool` message {tool_call_id, content:string} | **`output` 是 array 时未拍扁**（bug 02-#3） |
| `reasoning` | `id,summary,type` | passthrough 模式：拼到下一条 assistant 的 `reasoning_content` | drop 模式直接丢 |
| `web_search_call` / `file_search_call` / `computer_call` / `computer_call_output` / `image_generation_call` / `code_interpreter_call` / `local_shell_call` / `local_shell_call_output` / `function_shell_call` / `function_shell_call_output` / `apply_patch_tool_call` / `apply_patch_tool_call_output` / `mcp_call` / `mcp_list_tools` / `mcp_approval_request` / `mcp_approval_response` / `compaction_summary` / `tool_search_call` / `tool_search_output` / `custom_tool_call` / `custom_tool_call_output` | 各异 | guard 拒绝（部分类型）；其它 **fallthrough 静默 skip**（bug 02-#1，与裸消息同一类） |
| `item_reference` | `id` | guard 拒绝 |
| **裸消息**（无 type，仅 `role`+`content`） | EasyInputMessage 合法 | **`_input_items_to_messages` 不识别**（bug 02-#1，已知 P0） |

### 3.3 id ↔ call_id 关系

- `FunctionToolCall.id`：本次响应中 function_call item 的资源 id（`fc_…`）。
- `FunctionToolCall.call_id`：模型生成的 unique id，用来在 `function_call_output` / chat tool_calls 中回引（即 chat 端的 `tool_calls[i].id`）。
- 因此 chat→responses：`assistant.tool_calls[i].id` → responses 的 `call_id`，本代码同时合成一个 `id=fc_<call_id>` 当资源 id（OK）。
- responses→chat：item.call_id → chat tool_calls.id；chat 的 tool message.tool_call_id ← function_call_output.call_id。

---

## 4. content parts

### 4.1 Chat 端

| Chat part type | 字段 | spec |
|---|---|---|
| `text` | `text:string` | `ChatCompletionRequestMessageContentPartText` |
| `image_url` | `image_url:{url, detail?}` | `…ContentPartImage`（注：详细 enum=auto/low/high；spec 不带 `original`） |
| `input_audio` | `input_audio:{data, format∈{wav,mp3}}` | `…ContentPartAudio` |
| `file` | `file:{filename?, file_data?, file_id?}` | `…ContentPartFile` |
| `refusal` | `refusal:string` | `…ContentPartRefusal`（仅 assistant） |

`ChatCompletionRequestUserMessageContentPart` = oneOf {text, image_url, input_audio, file}  
`ChatCompletionRequestAssistantMessageContentPart` = oneOf {text, refusal}  
`ChatCompletionRequestSystemMessageContentPart` = `{text}`  
`ChatCompletionRequestToolMessageContentPart` = `{text}`

### 4.2 Responses 端（`InputContent`/`OutputContent`）

| Responses part type | 字段 | spec |
|---|---|---|
| `input_text` | `text` | `InputTextContent` |
| `input_image` | `image_url?, file_id?, detail` *required* | `InputImageContent`（detail enum=`ImageDetail`={low,high,auto,original}） |
| `input_file` | `file_id?, filename?, file_data?, file_url?, detail?` | `InputFileContent`（detail enum={low,high}） |
| `output_text` | `text, annotations[], logprobs[]` *all required* | `OutputTextContent` |
| `refusal` | `refusal:string` | `RefusalContent` |
| `reasoning_text` | `text` | `ReasoningTextContent`（仅出现在 ReasoningItem.content[]） |

注：Responses 端**没有 input_audio**！spec 里 `InputContent = oneOf {input_text, input_image, input_file}`。

### 4.3 双向映射表

| 场景 | Chat → Responses | Responses → Chat |
|---|---|---|
| 文本 | `text` ↔ `input_text`（chat user）/ `output_text`（chat assistant） | 反之 |
| 图片 | `image_url{url,detail}` → `input_image{image_url:url, detail}`（缺 `file_id` 字段未读取，bug 02-#4） | `input_image{image_url, detail}` → `image_url{url, detail}`；**`file_id` 字段被丢失**（bug 02-#4） |
| 文件 | `file{file_id?,file_data?,filename?}` → `input_file{file_id?,file_data?,filename?}`（**`file_url`/`detail` 未读未写**，bug 02-#5） | 反之，丢 `detail`/`file_url` |
| 音频 | `input_audio{data,format}` → guard 拦 |  responses 端无该 part，r2c 中代码生成了 `{type:input_audio,...}`（死代码 / bug 02-#6） |
| 拒绝 | `refusal{refusal}` → `refusal{refusal}` (output) | 反之；空 list 时 chat content 必须 null（02-#10） |
| 推理文本 | `reasoning_content` (delta SDK 非官方) → `reasoning` item.summary[`summary_text`] | reasoning item.summary/content → `reasoning_content`（合并丢失 summary vs reasoning_text 区分，bug 02-#19） |
| annotations | spec: `output_text.annotations[]` *required* | C→R 缺：本代码 emit 时给 `annotations: []`（OK）；R→C 中丢失 chat assistant.annotations[] 的回写（bug 02-#28） |
| logprobs | `output_text.logprobs[]` *required* | C→R 缺：emit 时不带 logprobs，但 spec 标 required（bug 02-#29） |

---

## 5. tools schema 映射

### 5.1 tools 数组项

| Chat tool 形态 | Responses 对应 | C→R `_flatten_tool` 行为 |
|---|---|---|
| `{type:function, function:{name,description?,parameters?,strict?}}` (`ChatCompletionTool` 引 `FunctionObject`) | `FunctionTool{type:function, name, description?, parameters?, strict, defer_loading?}` | 拷 name/description/parameters/strict（`strict` 在 responses 是 required，本代码**不补默认值**，bug 02-#30） |
| `{type:custom, custom:{name,description?,format?}}` (`CustomToolChatCompletions`) | `CustomTool{type:custom, name, description?, format?}` | **未实现**：当作 fallback 透传（bug 02-#26） |

Responses 端还存在一系列 built-in tools（`WebSearchTool`, `WebSearchPreviewTool`, `FileSearchTool`, `ComputerUsePreviewTool`, `CodeInterpreterTool`, `ImageGenTool`, `MCPTool`, `LocalShellTool`, `ApplyPatchTool`, `FunctionShellTool`），R→C 由 guard 拒绝。

### 5.2 tool_choice

| 形态 | Chat schema | Responses schema | 双向映射现状 |
|---|---|---|---|
| string `none/auto/required` | `ChatCompletionToolChoiceOption.string` (3 enum) | `ToolChoiceOptions` (3 enum) | ✅ 双向 string 透传 |
| 命名 function | `{type:function, function:{name}}` | `{type:function, name}` | ✅ 双向已实现 |
| 命名 custom | `{type:custom, custom:{name}}` | `{type:custom, name}` | ❌ 双向未实现（bug 02-#23） |
| allowed_tools | `{type:allowed_tools, allowed_tools:{mode,tools[]}}` | `{type:allowed_tools, mode, tools[]}` | ❌ 双向未实现（bug 02-#24） |
| hosted（built-in） | 不存在 | `{type:file_search\|web_search_preview\|computer\|computer_use_preview\|computer_use\|web_search_preview_2025_03_11\|image_generation\|code_interpreter}` | C→R 不需要；R→C **guard 未拦**（bug 02-#25） |
| MCP | 不存在 | `{type:mcp, server_label, name?}` | R→C **guard 未拦**（bug 02-#25） |
| ApplyPatch / FunctionShell | 不存在 | `SpecificApplyPatchParam` / `SpecificFunctionShellParam` | R→C **guard 未拦** |

---

## 6. usage 字段映射

### 6.1 Chat (`CompletionUsage`)

```
prompt_tokens (required)
completion_tokens (required)
total_tokens (required)
prompt_tokens_details:
  audio_tokens
  cached_tokens
completion_tokens_details:
  accepted_prediction_tokens
  audio_tokens
  reasoning_tokens
  rejected_prediction_tokens
```

### 6.2 Responses (`ResponseUsage`)

```
input_tokens (required)
input_tokens_details (required):
  cached_tokens (required)
output_tokens (required)
output_tokens_details (required):
  reasoning_tokens (required)
total_tokens (required)
```

### 6.3 双向映射

| Chat | ↔ | Responses |
|---|---|---|
| `prompt_tokens` | ↔ | `input_tokens` |
| `completion_tokens` | ↔ | `output_tokens` |
| `total_tokens` | ↔ | `total_tokens` |
| `prompt_tokens_details.cached_tokens` | ↔ | `input_tokens_details.cached_tokens` |
| `completion_tokens_details.reasoning_tokens` | ↔ | `output_tokens_details.reasoning_tokens` |
| `prompt_tokens_details.audio_tokens` | drop | — |
| `completion_tokens_details.audio_tokens` | drop | — |
| `completion_tokens_details.accepted_prediction_tokens` | drop | — |
| `completion_tokens_details.rejected_prediction_tokens` | drop | — |

代码现状（`_usage_resps_to_chat` / `_usage_chat_to_resps`）：核心字段映射 ✅；audio/prediction tokens 不传递 ✅（按规范 chat 上游若不返回这些字段属正常）。

**严重问题**：spec 把 `input_tokens_details.cached_tokens` 和 `output_tokens_details.reasoning_tokens` 标为 *required*。当前代码用 `if cached: res["input_tokens_details"]={…}`，**当 cached=0 / reasoning=0 时整段 details 缺失** —— 严格客户端反序列化 ResponseUsage 会失败（bug 02-#9）。

### 6.4 finish_reason ↔ status 完整对照

| Chat finish_reason | Responses status | incomplete_details.reason | 现状 |
|---|---|---|---|
| `stop` / null | `completed` | null | ✅ |
| `tool_calls` | `completed` | null | ✅ |
| `function_call` (legacy) | `completed` | null | ✅（同 tool_calls 处理） |
| `length` | `incomplete` | `max_output_tokens` | ✅ |
| `content_filter` | `incomplete` | `content_filter` | ✅ |
| (无对应) | `failed` | — | C→R: `_status_to_finish_reason` 兜底 `stop`/`tool_calls` |
| (无对应) | `cancelled` | — | C→R: 同 failed → stop |
| (无对应) | `queued` / `in_progress` | — | C→R: 兜底 stop（**理论上非流式 response 不会出现这俩**） |

---

## 7. 流式 SSE 事件映射

### 7.1 Chat chunk shape（`CreateChatCompletionStreamResponse`）

```
data: {
  "id":"chatcmpl-…",
  "object":"chat.completion.chunk",
  "created":<unix>,
  "model":"<model>",
  "choices":[{
    "index":0,
    "delta": {  // ChatCompletionStreamResponseDelta
      "role"?: "developer|system|user|assistant|tool",
      "content"?: string|null,
      "refusal"?: string|null,
      "tool_calls"?: [ChatCompletionMessageToolCallChunk{index,id?,type?,function?:{name?,arguments?}}],
      "function_call"? (deprecated)
    },
    "finish_reason"?: "stop|length|tool_calls|content_filter|function_call",
    "logprobs"?: object|null
  }],
  "usage"?: CompletionUsage|null  // 仅当 stream_options.include_usage=true 时末帧带
}
data: [DONE]
```

### 7.2 Responses 事件清单（`ResponseStreamEvent` anyOf 全部，按代码实际遇到顺序整理）

| event | payload schema | 备注 |
|---|---|---|
| `response.created` | `{type, response:Response, sequence_number}` | 必发 |
| `response.in_progress` | 同上 | 必发 |
| `response.queued` | 同上 | background 才出，本代理无 |
| `response.output_item.added` | `{type, output_index, item:OutputItem, sequence_number}` | 每个 output item 开始 |
| `response.content_part.added` | `{type, item_id, output_index, content_index, part:OutputContent, sequence_number}` | 每个 message content part 开始 |
| `response.output_text.delta` | `{type, item_id, output_index, content_index, delta, sequence_number, logprobs[]}` | text 增量；`logprobs` *required* |
| `response.output_text.done` | `{type, item_id, output_index, content_index, text, sequence_number, logprobs[]}` | text 完整 |
| `response.output_text.annotation.added` | `{type, item_id, output_index, content_index, annotation_index, annotation, sequence_number}` | 注释流（**当前代码未处理**） |
| `response.refusal.delta` | `{type, item_id, output_index, content_index, delta, sequence_number}` | refusal 增量 |
| `response.refusal.done` | `{type, item_id, output_index, content_index, refusal, sequence_number}` | refusal 完整 |
| `response.content_part.done` | 同 added，多个 part | content part 完整 |
| `response.output_item.done` | 同 added | output item 完整 |
| `response.function_call_arguments.delta` | `{type, item_id, output_index, delta, sequence_number}` | function_call 增量 |
| `response.function_call_arguments.done` | `{type, item_id, name, output_index, arguments, sequence_number}` | function_call 完整；**`name` *required*** |
| `response.reasoning_summary_part.added` | `{type, item_id, output_index, summary_index, part:{type:summary_text,text}, sequence_number}` | summary part 开始 |
| `response.reasoning_summary_part.done` | 同上 | summary part 完整 |
| `response.reasoning_summary_text.delta` | `{type, item_id, output_index, summary_index, delta, sequence_number}` | summary text 增量 |
| `response.reasoning_summary_text.done` | `{type, item_id, output_index, summary_index, text, sequence_number}` | summary text 完整 |
| `response.reasoning_text.delta` | `{type, item_id, output_index, content_index, delta, sequence_number}` | 原文 reasoning 增量 |
| `response.reasoning_text.done` | `{type, item_id, output_index, content_index, text, sequence_number}` | 原文 reasoning 完整 |
| `response.completed` | `{type, response:Response, sequence_number}` | 终态成功 |
| `response.incomplete` | 同上 | 终态 incomplete（length/content_filter） |
| `response.failed` | 同上（response.error 必填） | 终态失败 |
| `error` | `{type:error, code, message, param, sequence_number}` | 通用错误 |
| 多种 built-in tool call 事件（web_search_call / file_search_call / code_interpreter_call / image_gen_call / mcp_call / mcp_list_tools / audio / audio_transcript / custom_tool_call_input） | 各异 | guard 已拒绝相关 tool；忽略即可 |

### 7.3 时序对照（Responses 上游 → Chat 下游 = stream_r2c）

| Responses 事件序 | Chat chunk 行为 | 现状 |
|---|---|---|
| `response.created` / `in_progress` | 不发（chat 没对应） | ✅ |
| `output_item.added` (item.type=function_call) | 发 `delta:{role:assistant?, tool_calls:[{index,id,type:function,function:{name,arguments:""}}]}`；首个 fc 前带 role chunk | ✅ |
| `output_item.added` (item.type=message) | **不发**（懒到首个 text delta） | ⚠️ 多 message item 切换会丢段落（bug 02-#33） |
| `output_item.added` (item.type=reasoning) | **不发** | OK，懒到首个 reasoning delta |
| `output_text.delta` | 发 `delta:{content}` + 必要时前置 role chunk | ✅ |
| `refusal.delta` | 发 `delta:{refusal}` | ✅ |
| `reasoning_summary_text.delta` / `reasoning_text.delta` | 发 `delta:{reasoning_content}`（非官方字段） | ✅（drop 模式丢） |
| `function_call_arguments.delta` | 发 `delta:{tool_calls:[{index, function:{arguments}}]}` | ✅ |
| `content_part.added/done` / `output_text.done` / `refusal.done` / `output_item.done` / `reasoning_summary_part.*` / `reasoning_summary_text.done` / `function_call_arguments.done` | **忽略** | ✅ chat 端不需要边界 |
| `output_text.annotation.added` | **忽略** | ⚠️ chat annotations 字段丢失（bug 02-#28/35） |
| `response.completed` / `response.incomplete` | 暂存 usage + finish_reason，由 close() 统一发 finish_reason chunk + 可选 usage chunk + `[DONE]` | ✅ |
| `response.failed` / `error` | 立即发 `{error:{...}}` 帧 + `[DONE]` | ⚠️ error.code 没保留（bug 02-#7） |

### 7.4 时序对照（Chat 上游 → Responses 下游 = stream_c2r）

| Chat chunk → | Responses 事件序 | 现状 |
|---|---|---|
| 首 chunk（任意 delta） | `response.created` + `response.in_progress` | ✅ skeleton 不全（bug 02-#13） |
| `delta.content` 首次 | `response.output_item.added(item:message)` + `response.content_part.added(part:output_text)` + `response.output_text.delta` | ✅ |
| `delta.content` 后续 | `response.output_text.delta` | ✅ |
| `delta.reasoning_content` 首次 | `response.output_item.added(item:reasoning)` + `response.reasoning_summary_part.added` + `response.reasoning_summary_text.delta` | ✅ |
| `delta.reasoning_content` 后续 | `response.reasoning_summary_text.delta` | ✅ |
| `delta.refusal` 首次 | （前置切回 message）`response.content_part.added(part:refusal)` + `response.refusal.delta` | ⚠️ content_index 计算可能与 text part 撞车（bug 02-#16） |
| `delta.refusal` 后续 | `response.refusal.delta` | ✅ |
| `delta.tool_calls[i]` 首次 | （前置 close text/reasoning）`response.output_item.added(item:function_call)` + 可选 `response.function_call_arguments.delta` | ✅ |
| `delta.tool_calls[i]` 后续 | `response.function_call_arguments.delta` | ✅ |
| `delta.tool_calls[i]` 是 custom 类型 | 应映射 `response.custom_tool_call_input.delta` 等 | ❌ 完全不处理（bug 02-#27） |
| `finish_reason` | 暂存，由 close() 收尾 | ✅ |
| `usage` (末 chunk) | 暂存到 state.usage | ✅ |
| `[DONE]` / 流结束 | close() 关闭未关 items；发 `response.completed`/`response.incomplete`/`response.failed` | ⚠️ done 事件多个 required 字段缺失（bug 02-#14、#17） |
| 上游 `{error:{}}` | 暂存到 state.terminal_error；close() 发 `response.failed` | ⚠️ response.failed.response.error.code 不在 enum（bug 02-#8） |

### 7.5 sequence_number / output_index / content_index / item_id 一致性

- spec 要求所有事件均有 `sequence_number` *required*（自增） — `stream_c2r.C2RState.next_seq()` ✅；`stream_r2c` 不发任何 responses 事件（chat 下游不需要）
- `output_index` 在同一 response 内单调递增；`stream_c2r.allocate_output_index()` ✅
- `content_index` 在同一 output item 内单调递增；当前实现假设 message 只有 0=text、1=refusal 两个 content_index（bug 02-#16）
- `item_id`：`msg_<uuid>` / `rs_<uuid>` / `fc_<uuid>` 都是 24 字符 hex，OK
- `summary_index`：当前固定 0；spec 允许多 summary_part（bug 02-#34）
- `name` 字段：`response.function_call_arguments.done` 必带，本代码漏（bug 02-#17）

---

## 8. guard 总览

| 入口 | 检查项 | 处理 |
|---|---|---|
| chat ingress | `n>1` | 400 |
| chat ingress | `modalities` 含 audio | 400 |
| responses ingress | `background` 字段 | 静默剥除（无论 true/false） |
| responses ingress | `conversation` 非空 | 400 |
| responses ingress | `previous_response_id` 但 store off | 400 |
| chat→responses 跨变体 | `n>1` | 400（防御） |
| chat→responses | `logprobs/top_logprobs` | 400 |
| chat→responses | message.content 含 `input_audio` | 400 |
| chat→responses | tool_choice {allowed_tools/custom/...} | **未拦**（bug 02-#23/24） |
| chat→responses | tools 含 custom | **未拦**（bug 02-#26） |
| chat→responses | messages 含 role=function | **未拦**（bug 02-#15） |
| chat→responses | tool_calls 含 type=custom | **未拦**（bug 02-#27） |
| responses→chat | tools 含非 function 类型 | 400（white-list 包含 web_search_preview/file_search/computer_use_preview/code_interpreter/image_generation/mcp/local_shell；**缺 web_search/computer/computer_use/apply_patch/function_shell**，bug 02-#21） |
| responses→chat | input items 含 built-in call types | 400 |
| responses→chat | input items 含 `item_reference` | 400 |
| responses→chat | `previous_response_id` 但 store off | 400 |
| responses→chat | `conversation` 非空 | 400 |
| responses→chat | `include` 含 `reasoning.encrypted_content` | 静默剥除 |
| responses→chat | `tool_choice` {hosted/mcp/allowed_tools/custom} | **未拦**（bug 02-#25） |
| responses→chat | input items 中**无 type 字段**的裸消息 | 放行（spec 合法） — translate 对应处理见 02-#1 |
| responses→chat | `text.format`/`reasoning.summary`/`max_tool_calls`/`truncation`/`prompt`/`context_management` | 不拦（部分丢失） |

---

完。下一份：`02-bug-findings.md`。

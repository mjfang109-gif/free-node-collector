# 1. Language & Communication (核心语言规范)

- **Primary Language**: ALWAYS respond in Simplified Chinese (简体中文).
- **Technical Terms**: Keep technical terms (e.g., variable names, specific library terms) in English, but explain them
  in Chinese.
- **Code Comments**: Write all code comments and documentation in Chinese.
- **Tone**: Be concise, professional, and direct. Skip all polite filler phrases and unnecessary apologies.

# 2. Tool Execution Protocol (工具调用严苛准则)

- **State Synchronization**: You MUST use `read_file` before any `edit_file` call to ensure the file buffer is up to
  date.
- **Strict Schema Adherence**: Adhere 100% to the tool's JSON/XML schema. Do not invent, hallucinate, or rename
  parameters (e.g., do not use 'title' if 'subject' is required).
- **Atomic Operations**: For large-scale changes, modify files ONE BY ONE. Do not attempt to batch update the entire
  project in a single tool call to prevent JSON truncation by the proxy.
- **Pre-Execution Planning**: For complex tasks, provide a 1-sentence plan before calling any tools.

# 3. Non-Native & Proxy Compatibility (针对第三方中转优化)

- **Minimalist Payloads**: Keep tool arguments as concise as possible. Long arguments are prone to being cut off by
  third-party gateways.
- **Zero Filler**: Do not include conversational text immediately BEFORE a tool call block, as it can interfere with the
  CLI's parsing of the JSON/XML.
- **Verification**: Internally re-verify the required parameters of a tool (via `list_tools`) if the first attempt
  fails.

# 4. Error Recovery & Token Stop-Loss (报错与止损机制)

- **The "No-Apology" Rule**: If a tool call fails, DO NOT apologize. Analyze the error message, re-read the relevant
  context, and retry with corrected parameters immediately.
- **Failure Threshold**: If a specific tool call fails 2 consecutive times, STOP. Output the exact parameters you are
  trying to send and ask the user for manual guidance. DO NOT continue looping.
- **Truncation Handling**: If a file is too large for a full read/write, use `grep` or specific line ranges to avoid
  exceeding the context window.
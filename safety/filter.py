import re

# Input blocklist patterns (obvious violations)
INPUT_BLOCK_PATTERNS = [
    # Profanity (Chinese common profanity)
    r"他妈的", r"操你", r"傻[逼比]", r"滚蛋", r"草泥马",
    # AI breakout / prompt injection
    r"忽略.{0,4}(以上|上面|前面).{0,4}(所有|全部)?(指令|规则|提示)",
    r"ignore.{0,4}(all|previous|above).{0,4}(instructions|rules|prompts)",
    r"(system|developer|admin)\s*prompt",
    r"你(是|作为一个?)(AI|人工智能|大模型|语言模型|GPT|ChatGPT|Claude)",
    r"reveal\s+(your|the)\s+(system|secret|hidden)",
]

# Output rewrite patterns (AI self-identification)
OUTPUT_AI_PATTERNS = [
    (r"作为一?[个名]?(AI|人工智能|大模型|大语言模型|语言模型)[，,]?",
     "作为一个修仙世界的修道者，"),
    (r"我是?(AI|人工智能|大模型|大语言模型|语言模型)[，,]?",
     "我是"),
    (r"(由|被)(DeepSeek|OpenAI|Anthropic|Z\.?AI|Google).{0,6}(训练|开发|创建|设计|制造)",
     "修炼有成，在青云门修行多年"),
    (r"我不能.{0,10}(帮|提供|做|回答|告诉)",
     "此乃天机，不可轻泄，"),
]

# Compile patterns
INPUT_BLOCK_RE = [re.compile(p, re.IGNORECASE) for p in INPUT_BLOCK_PATTERNS]
OUTPUT_REWRITE_RE = [(re.compile(p, re.IGNORECASE), replacement) for p, replacement in OUTPUT_AI_PATTERNS]


def pre_filter_input(text: str) -> tuple[str, bool]:
    """
    Pre-filter player input.
    Returns (text, was_blocked). If blocked, the text is the rejection message.
    """
    for pattern in INPUT_BLOCK_RE:
        if pattern.search(text):
            return "【系统】此言不雅，修仙之路当正心诚意。", True
    return text, False


def post_filter_output(text: str) -> tuple[str, bool]:
    """
    Post-filter DM output to rewrite AI self-identification.
    Returns (filtered_text, was_rewritten).
    """
    was_rewritten = False
    result = text
    for pattern, replacement in OUTPUT_REWRITE_RE:
        if pattern.search(result):
            result = pattern.sub(replacement, result)
            was_rewritten = True
    return result, was_rewritten
import re

SUSPICIOUS_PATTERNS = (
    re.compile(r"ignore (all |any )?(previous|prior|system) instructions", re.I),
    re.compile(r"reveal|show|print|return.{0,20}(system prompt|api key|password|secret)", re.I),
    re.compile(r"developer mode|jailbreak|do anything now", re.I),
    re.compile(r"execute.{0,20}(shell|python|sql)|drop table", re.I),
)


def detect_prompt_injection(text: str) -> str | None:
    """Catch obvious attacks; deterministic authorization remains the real control."""
    for pattern in SUSPICIOUS_PATTERNS:
        if pattern.search(text):
            return (
                "The request appears to contain an instruction-override or secret-access attempt."
            )
    return None

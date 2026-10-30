"""National Bank Investments FMC profile."""

from .base import FMCProfile

PROFILE = FMCProfile(
    key='nbi',
    label='National Bank Investments',
    signature=(
        r'National Bank Investments',
        r'www\.nbinvestments\.ca',
        r'\bNBI Sustainable\b',
    ),
    title_re=(
        r'(?m)^[ \t]*'
        r'(NBI(?:[ \t]+[A-Za-z][A-Za-z0-9&\'’.-]*){2,12}'
        r'[ \t]+(?:Fund|Portfolio|Class))'
        r'[ \t]*$'
    ),
    class_style='nbi',
)

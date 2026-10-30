"""Dynamic / 1832 Asset Management stacked annual ratios."""
from .base import FMCProfile
PROFILE=FMCProfile(
    key='dynamic',label='1832 Asset Management (Dynamic)',
    signature=(r'1832 Asset Management L\.P\.',r'www\.dynamic\.ca',r'\bDynamic Dividend\b'),
    title_re=r'(?m)^\s*(Dynamic\s+[^\n]{3,110}(?:Fund|Class|Portfolio))\s*$',
)

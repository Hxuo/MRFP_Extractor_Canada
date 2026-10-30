"""Desjardins class-sliced ratio tables; class labels 'A-CLASS', 'T5-CLASS'."""
from .base import FMCProfile
PROFILE=FMCProfile(
    key='desjardins',label='Desjardins Investments',
    signature=(r'\bDESJARDINS FUNDS\b',r'\bDesjardins Investments Inc\.',r'desjardinsfunds\.com'),
    title_re=r'(?m)^\s*(Desjardins\s+[^\n]{4,110}(?:Fund|Portfolio))\s*$',
    class_style='desjardins',
    section_re=r'Desjardins\s+.{4,110}(?:Fund|Portfolio)',
)

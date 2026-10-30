"""Manulife: Advisor, Series F/FT/O/T in repeating financial tables."""
from .base import FMCProfile
PROFILE=FMCProfile(
    key='manulife',label='Manulife Investment Management',
    signature=(r'Manulife Investment Management Limited',r'manulifeim\.ca',r'\bManulife\b'),
    title_re=r'(?m)^\s*(Manulife\s+[^\n]{3,120}(?:Fund|Class|Portfolio))\s*$',
)

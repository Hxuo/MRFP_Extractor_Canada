"""Purpose: ETF Units and mutual fund Class A/F with year-only date headers."""
from .base import FMCProfile
PROFILE=FMCProfile(
    key='purpose',label='Purpose Investments',
    signature=(r'www\.purposeinvest\.com',r'\bPurpose Investments\b',r'\bPURPOSE ACTIVE BALANCED FUND\b'),
    title_re=r'(?m)^\s*(PURPOSE\s+[^\n]{3,110}(?:FUND|PORTFOLIO))\s*$',
)

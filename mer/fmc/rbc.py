"""RBC GAM: year-as-rows ratio matrix and leading product-category headers."""
from .base import FMCProfile
PROFILE=FMCProfile(
    key='rbc',label='RBC Global Asset Management',
    signature=(r'RBC Global Asset Management Inc',r'www\.rbcgam\.com',r'\bRBC CANADIAN CORPORATE\b'),
    title_re=r'(?m)^\s*(RBC\s+[^\n]{3,110}(?:FUND|PORTFOLIO))\s*$',
)

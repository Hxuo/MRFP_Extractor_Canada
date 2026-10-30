"""Franklin Templeton: Series A/F/O and ETF Series on financial highlight pages."""
from .base import FMCProfile
PROFILE=FMCProfile(
    key='franklin',label='Franklin Templeton',
    signature=(r'franklintempleton\.ca',r'Franklin Templeton Investments Corp',r'\bFRANKLIN CANADIAN\b'),
    title_re=r'(?m)^\s*(FRANKLIN\s+[^\n]{3,130}(?:FUND|PORTFOLIO))\s*$',
)

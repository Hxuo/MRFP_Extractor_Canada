"""Sun Life / SLGI multi-line ratio labels and horizontally aligned years."""
from .base import FMCProfile
PROFILE=FMCProfile(
    key='sun_life',label='SLGI Asset Management (Sun Life)',
    signature=(r'SLGI ASSET MANAGEMENT INC\.',r'sunlifeglobalinvestments\.com',r'\bSun Life Granite\b'),
    title_re=r'(?m)^\s*(Sun Life\s+[^\n]{3,100}(?:Fund|Class|Portfolio))\s*$',
    class_style='sun_life',
)

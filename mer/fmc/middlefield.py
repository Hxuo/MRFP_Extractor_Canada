"""Middlefield report may mention many unrelated investment funds in commentary."""
from .base import FMCProfile
PROFILE=FMCProfile(
    key='middlefield',label='Middlefield',
    signature=(r'\bMIDDLEFIELD\s+(?:MUTUAL FUNDS|GLOBAL|LIMITED)\b',r'MIDDLEFIELD CORPORATE PROFILE',r'\bMiddlefield Limited\b'),
    # Legacy layout-based title discovery supports arbitrary Middlefield funds.
)

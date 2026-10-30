"""BlackRock / iShares: ETFs can have fund-name-as-class and no TER."""
from .base import FMCProfile
PROFILE=FMCProfile(
    key='blackrock',label='BlackRock / iShares',
    signature=(r'BlackRock Asset Management Canada Limited',r'www\.blackrock\.com/ca',r'\biShares\b'),
    # Use the native title normalizer for ETFPortfolio and 1-5Year spacing.
)

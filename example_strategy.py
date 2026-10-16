"""
IDEA: trend following -- long while the 20-hour average is above the 100-hour average, short while below.

A format example, not a suggestion. Uses bars up to the current one only.
"""
import numpy as np
import pandas as pd


def positions(df: pd.DataFrame) -> pd.Series:
    fast = df["close"].rolling(20).mean()
    slow = df["close"].rolling(100).mean()
    pos = np.sign(fast - slow)
    return pd.Series(pos, index=df.index).fillna(0).astype(int)

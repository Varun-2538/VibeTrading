"""
Pure analysis over candles.

Nothing in this package performs I/O. Every function takes a list of candles
and returns a result, which keeps the detectors testable against fixtures and
lets the same code run over a whole series or over just the slice a trader has
on screen.
"""

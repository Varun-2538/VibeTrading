# W/M pattern detection

Date: 2026-08-07
Status: approved, not yet implemented
Slice: 2 of 4

## Why

Slice 1 established that the backend can analyse exactly the candles a trader is
looking at. This slice puts the first real analysis through that seam: double
bottoms and double tops, marked on the chart while they are still forming.

Only W and M. Head and shoulders, flag and pole, and cup and handle reuse the
same pipeline and follow in slice 3, once the pipeline is proven on the simplest
pattern.

## Decisions already taken

**Three states, visually distinct.** A pattern is marked while forming, again
once price is in its final leg near the neckline, and again once the neckline
breaks. Marking only confirmed breaks would be purely descriptive - it reports
what already happened and drops the "about to complete" case entirely. Marking
everything identically would make an early guess look like a confirmed call, so
the states are styled differently and the label says which one it is.

**Strictness is a control, not a constant.** Strict, balanced and loose presets
are exposed in the chart header rather than picked blind. Whether a given wobble
is a double bottom is a matter of trading judgement, and that judgement is
better made against real charts than in a design document.

**Thresholds scale with volatility, never fixed percentages.** Slice 1 shipped a
bug where a flat 2% clustering tolerance made support impossible to find on a 1m
chart, because a thousand one-minute candles span less than the tolerance. Every
threshold here is expressed in ATR so the same detector behaves sensibly on 1m
and 1d.

**No preceding-trend requirement.** Several published implementations only
accept a double bottom if a downtrend preceded it, on the textbook grounds that
it is a reversal pattern. We deliberately do not. Small W's and M's that form
inside a range are real setups that scalpers trade, and a prior-trend filter
would delete exactly those by definition. This also rules out ZigZag pivot
filtering, which most references use: its minimum-retracement threshold
suppresses small turns, which is what intra-range patterns are made of.

ATR thresholds are what make this workable - a quiet range has a small ATR, so
a shallow pattern inside it still clears the depth requirement, and the loose
preset is effectively the scalping setting.

**Geometry on wicks, breaks on closes.** Pivots are measured on highs and lows
by default, matching classic technical analysis and most published
implementations, with a toggle for closes because crypto stop hunts routinely
print equal wick lows that mean nothing. A break is always a close beyond the
neckline whichever source is selected: a wick through it is not a break.

**Threshold units, validated against published scripts.** The widely copied
Pine defaults are percentages - 2% shoulder tolerance, 5% depth. On BTC those
work out to 0.9 and 2.2 ATR on a daily chart, close to our 0.5 and 1.5, but to
65 and 164 ATR on a 1m chart. Those scripts are calibrated for daily charts and
break intraday in both directions at once: any two lows match, and no pattern
is ever deep enough. This is the same failure the level clustering had.

**Chat gets a keyword branch, not tool-calling.** detect_query_intent in
chat_controller routes by substring matching, not by asking the model. Patterns
get another branch, which works but requires enumerating phrasings by hand.
Replacing that matcher with real tool-calling is worth doing and touches every
existing intent, so it is its own slice rather than a rider on this one.

## Architecture

### analysis/patterns.py

Pure, no I/O, same shape as analysis/levels.py: candles in, results out. That is
what lets it run over a viewport slice, and what makes it testable against
fixtures.

```
detect_double_patterns(candles, strictness="balanced", kinds=("W", "M"))
    -> list[Pattern]
```

Steps:

1. **ATR** over the window, giving every later threshold a unit that means the
   same thing on any timeframe.
2. **Swing pivots** - a pivot low is the lowest close within k bars either side;
   pivot highs mirror it. k comes from the strictness preset.
3. **Pairing** - for each pair of pivot lows with a pivot high between them:
   - the lows match within `tol x ATR`
   - the neckline (that intervening high) sits at least `depth x ATR` above the
     higher of the two lows
   - the lows are between `min_bars` and `max_bars` apart
4. **State**, from where price is now:
   - `confirmed` - some close after the second low is above the neckline
   - `approaching` - price is rising off the second low and within `near x ATR`
     of the neckline
   - `forming` - the second low is in and price has turned up, but is further
     from the neckline than that
5. **M** is the same procedure with highs and lows exchanged and the comparisons
   inverted.

**Confidence** is 0-100 built from three geometric terms, each reported
alongside the total so a score can always be explained:

- *similarity* - how closely the two lows match, relative to the tolerance
- *depth* - how far the neckline sits above the lows, relative to the minimum
- *symmetry* - how alike the two legs are in duration

No volume term. Volume would strengthen the signal but is a separate argument
about what counts as confirmation, and mixing it in now would make a low score
impossible to attribute.

Overlapping detections that share a pivot are collapsed to the highest
confidence, and results are capped per window so a noisy chart cannot bury the
price action under marks.

### Strictness presets

| | tol | depth | near | bars | pivot k |
|---|---|---|---|---|---|
| strict | 0.25 ATR | 2.5 ATR | 0.2 ATR | 12-120 | 5 |
| balanced | 0.5 ATR | 1.5 ATR | 0.3 ATR | 8-120 | 4 |
| loose | 1.0 ATR | 1.0 ATR | 0.5 ATR | 5-150 | 3 |

### Endpoint

```
POST /api/analysis/patterns
  { symbol, timeframe, from, to, kinds: ["W","M"], strictness: "balanced" }
```

Same window shape as /api/analysis/levels, as slice 1 planned. Each pattern
returns its points as both timestamps and prices, so the frontend can position
geometry without recomputing anything:

```
{
  kind: "W",
  state: "approaching",
  confidence: 82,
  components: { similarity: 91, depth: 74, symmetry: 80 },
  points: { low1: {time, price}, peak: {time, price}, low2: {time, price} },
  neckline: 64750.0,
  target: 65200.0          // neckline + pattern height, the measured move
}
```

### SVG overlay

A W is diagonal polylines plus a horizontal neckline segment, and Lightweight
Charts price lines only draw horizontals, so the overlay planned in slice 1 is
built here. An absolutely positioned SVG sits above the canvas and positions
everything through timeToCoordinate() and priceToCoordinate(), redrawing on pan,
zoom and resize.

Styling per state: forming is faint and dashed with no label, approaching is
solid with a confidence label, confirmed is filled and labelled with its target.

## Error handling

- Fewer candles than the ATR period or the minimum separation: return no
  patterns rather than an error, and clear the overlay.
- A flat window where ATR is zero: return no patterns; every threshold would
  otherwise collapse to zero and match everything.
- Unknown strictness or kind: 400 listing accepted values.
- The overlay redraws from the last successful response, so a failed request
  leaves the previous marks rather than blanking the chart mid-pan.

## Testing

Detector, against synthetic fixtures:

- A textbook W is found, with both lows and the neckline at the expected prices.
- The same W truncated before the neckline break reports `approaching`, and
  truncated again before that reports `forming`.
- A W whose second low is far below the first is rejected at balanced strictness.
- A shallow wobble below the depth threshold is rejected.
- Pure noise produces nothing.
- An M is found in the mirror image of the W fixture.
- The same fixture scaled to 1m-sized moves and to 1d-sized moves is detected
  identically, which is the regression guard for the fixed-percentage bug.
- Strict finds no more patterns than balanced, which finds no more than loose.

Frontend: overlay geometry lands on the right candles after panning and zooming;
switching strictness re-requests and redraws; switching timeframe clears.

## Done when

On a 1m BTC chart, a developing double bottom is marked faintly as it forms,
turns solid with a confidence figure as price makes its final approach to the
neckline, and fills in with a measured target once it breaks. Switching
strictness visibly changes what is marked. Asking chat about a double bottom
returns the same patterns the chart is showing.

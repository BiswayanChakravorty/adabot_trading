# Risk Management

Risk controls are deterministic and are applied after AI signal generation.

## Capital

The configured total capital is INR 3,000 and the nominal per-trade allocation is INR 1,000. The allocation is capped so that a single trade cannot exceed total configured capital.

## BUY validation

A BUY signal must:

- use the BUY action;
- reference an asset present in the current market snapshot;
- contain a positive, finite entry price;
- remain within the configured maximum entry-price deviation from the observed price.

## Target and stop

The current constants define a 10% target and a 3% maximum-risk stop distance. The calculated risk/reward ratio is checked against the configured minimum of 2.0.

## Important scope

These controls are pre-trade calculations and alert filters. They are not broker-enforced risk controls because the project does not execute orders.


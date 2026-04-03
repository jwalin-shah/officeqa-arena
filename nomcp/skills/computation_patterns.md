# Computation Patterns

ALL arithmetic MUST use python3. Never compute in your head.

## Basic Operations
```bash
# Sum monthly values
python3 -c "print(sum([132, 129, 143, 159, 154, 153, 177, 200, 219, 287, 376, 473]))"

# Percent change (absolute)
python3 -c "print(round(abs((44463 - 2602) / 2602) * 100, 2))"

# Difference
python3 -c "print(44463 - 2602)"

# Average/Mean
python3 -c "vals = [100, 200, 300]; print(round(sum(vals)/len(vals), 2))"

# Ratio
python3 -c "print(round(44463 / 2602, 2))"
```

## Statistics
```bash
# Standard deviation
python3 -c "import statistics; print(round(statistics.stdev([100, 200, 300]), 2))"

# Median
python3 -c "import statistics; print(statistics.median([100, 200, 300]))"

# Geometric mean
python3 -c "import statistics; print(round(statistics.geometric_mean([100, 200, 300]), 2))"

# Coefficient of variation
python3 -c "import statistics; vals=[100,200,300]; print(round(statistics.stdev(vals)/statistics.mean(vals)*100, 2))"
```

## Growth Rates
```bash
# CAGR (Compound Annual Growth Rate)
python3 -c "start=100; end=200; years=5; print(round(((end/start)**(1/years)-1)*100, 2))"

# Year-over-year growth
python3 -c "old=100; new=150; print(round((new-old)/abs(old)*100, 2))"
```

## CPI Inflation Adjustment
```bash
# Adjust 1940 value to 1953 dollars
python3 -c "nominal=2602; cpi_1940=14.0; cpi_1953=26.7; print(round(nominal * cpi_1953/cpi_1940, 2))"
```

## Unit Conversion
```bash
# Convert "in thousands" to "in millions"
python3 -c "val_thousands=1234567; print(round(val_thousands / 1000, 2))"

# Convert "in millions" to actual dollars
python3 -c "val_millions=2602; print(val_millions * 1000000)"
```

## Cleaning Values
```bash
# Strip commas and footnotes from a value
python3 -c "
import re
raw = '1,580 3/'
clean = re.sub(r'[,\s]', '', re.sub(r'\s*\d+/', '', raw))
print(float(clean))
"
```

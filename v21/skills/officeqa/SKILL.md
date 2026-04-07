---
name: officeqa
description: Treasury Bulletin data extraction tool + verification checklist + CPI + compute recipes
---

## Pre-deployed query tool

A combined search + table parser is ready at:
```
EXT="$HOME/Library/Application Support/goose/extensions/officeqa"
```

### Search across files + parse tables:
```
python3 "$EXT/q.py" "keyword"                              # find which files have the keyword
python3 "$EXT/q.py" "keyword" --row "defense"              # search + extract matching rows
python3 "$EXT/q.py" "keyword" --row "1940" --col "defense" # search + specific cell
```

### Parse a specific file:
```
python3 "$EXT/q.py" FILE --rows                  # list all row labels
python3 "$EXT/q.py" FILE --cols                  # list all column headers
python3 "$EXT/q.py" FILE --row "defense"         # extract all columns for matching rows
python3 "$EXT/q.py" FILE --row "1940" --col "yr" # specific cell
python3 "$EXT/q.py" FILE --row "def" --fuzzy     # fuzzy match
```

Output is vertical: `ROW: label` then `column = value` per line. Units shown at top.

## Verification checklist (check BEFORE writing final answer)
- Right row? Re-read the label. "Total" is not the specific line item.
- Right section? Scroll up to find the section heading.
- Right column/year? Count columns from the header row.
- Net vs Gross? Check which the question asks.
- Units? Table header says millions, billions, thousands, or percent.
- Parentheses = negative: (123) means -123.
- FY months: pre-1977 = Jul-Jun, post-1976 = Oct-Sep. CY = Jan-Dec.
- Formula: pct_change = (new-old)/old*100, NOT /new.
- Magnitude check: Federal budgets are billions, not millions.

## Fiscal year rules
- FY pre-1977: Jul 1 (Y-1) to Jun 30 (Y). FY1953 = Jul 1952–Jun 1953.
- FY post-1976: Oct 1 (Y-1) to Sep 30 (Y). FY2024 = Oct 2023–Sep 2024.
- Transition quarter: Jul–Sep 1976.
- Bulletin year ≠ data year. A 1941 bulletin reports FY1940 data.

## CPI-U annual averages (BLS, base 1982-84=100):
1913:9.9 1914:10.0 1915:10.1 1916:10.9 1917:12.8 1918:15.1 1919:17.3
1920:20.0 1921:17.9 1922:16.8 1923:17.1 1924:17.1 1925:17.5 1926:17.7
1927:17.4 1928:17.2 1929:17.2 1930:16.7 1931:15.2 1932:13.6 1933:12.9
1934:13.4 1935:13.7 1936:13.9 1937:14.4 1938:14.1 1939:13.9 1940:14.0
1941:14.7 1942:16.3 1943:17.3 1944:17.6 1945:18.0 1946:19.5 1947:22.3
1948:24.1 1949:23.8 1950:24.1 1951:26.0 1952:26.5 1953:26.7 1954:26.9
1955:26.8 1956:27.2 1957:28.1 1958:28.9 1959:29.1 1960:29.6 1961:29.9
1962:30.2 1963:30.6 1964:31.0 1965:31.5 1966:32.4 1967:33.4 1968:34.8
1969:36.7 1970:38.8 1971:40.5 1972:41.8 1973:44.4 1974:49.3 1975:53.8
1976:56.9 1977:60.6 1978:65.2 1979:72.6 1980:82.4 1981:90.9 1982:96.5
1983:99.6 1984:103.9 1985:107.6 1986:109.6 1987:113.6 1988:118.3
1989:124.0 1990:130.7 1991:136.2 1992:140.3 1993:144.5 1994:148.2
1995:152.4 1996:156.9 1997:160.5 1998:163.0 1999:166.6 2000:172.2
2001:177.1 2002:179.9 2003:184.0 2004:188.9 2005:195.3 2006:201.6
2007:207.3 2008:215.3 2009:214.5 2010:218.1 2011:224.9 2012:229.6
2013:233.0 2014:236.7 2015:237.0 2016:240.0 2017:245.1 2018:251.1
2019:255.7 2020:258.8 2021:271.0 2022:292.7 2023:304.7 2024:314.2
real = nominal × (target_cpi / source_cpi)

## Computation recipes
- Sum monthly: `python3 -c "print(sum([v1,...,v12]))"`
- Pct change: `python3 -c "print((NEW-OLD)/OLD*100)"`
- Stdev (sample): `python3 -c "import statistics; print(statistics.stdev([...]))"`
- Stdev (pop): `statistics.pstdev([...])`
- Regression: `r=statistics.linear_regression(xs,ys); print(r.slope,r.intercept)`
- Correlation: `statistics.correlation(xs,ys)`
- CAGR: `print(((END/START)**(1/YEARS)-1)*100)`

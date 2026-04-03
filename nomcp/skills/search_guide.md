# How to answer Treasury Bulletin questions

You MUST follow these exact steps. Do NOT explore the filesystem or run ls.

## Step 1: Build index (ONCE)
```
python3 /installed-agent/build_index.py
```

## Step 2: Search the index
```
grep -i "national defense" /tmp/keyword_index.txt | head -10
grep -i "veterans.*admin" /tmp/keyword_index.txt | grep "1944" | head -10
```
NEVER grep /app/corpus/ directly. ALWAYS grep /tmp/keyword_index.txt.

## Step 3: Read table
```
python3 /installed-agent/search.py table treasury_bulletin_1941_01.txt 248
```

## Step 4: Compute
```
python3 -c "print(sum([132, 129, 143, 159, 154, 153, 177, 200, 219, 287, 376, 473]))"
```

## Step 5: Submit
```
echo -n "2,602" > /app/answer.txt
```

Finish in 6-8 commands total. After 10 commands, submit immediately.

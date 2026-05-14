import subprocess
import re
import json

# Run arena history and capture raw output
result = subprocess.run(['arena', 'history'], capture_output=True, text=True)
output = result.stdout

# Extract ID patterns (UUID format: 8-4-4-4-12 hex digits)
# From the table, we can see truncated IDs like "731c7235-9a…"
# We need to use arena traces or status to get full IDs

# Alternative: check if there's a way to get full IDs from arena CLI
print("Trying arena traces with truncated ID...")
result2 = subprocess.run(['arena', 'traces', '731c7235'], capture_output=True, text=True)
print(result2.stdout)
print(result2.stderr)

# Try status command
print("\nTrying arena status with truncated ID...")
result3 = subprocess.run(['arena', 'status', '731c7235'], capture_output=True, text=True)
print(result3.stdout)
print(result3.stderr)

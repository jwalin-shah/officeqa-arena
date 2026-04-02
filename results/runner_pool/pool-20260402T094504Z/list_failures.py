import json
import os
import glob
from collections import defaultdict

reports_dir = "results/runner_pool/pool-20260402T094504Z/deep_trials/reports/"
reports = glob.glob(os.path.join(reports_dir, "*.json"))

failures = defaultdict(list)

for report_path in reports:
    with open(report_path, "r") as f:
        data = json.load(f)
        uid = data.get("uid")
        reward = data.get("reward", 0.0)
        
        if reward < 1.0:
            exc = data.get("exception_preview", "") or ""
            verif = data.get("verifier_stdout", "") or ""
            
            if "137" in exc:
                failures["Tool Spiraling/Timeout"].append(uid)
            elif "not found" in verif:
                failures["Missing answer.txt"].append(uid)
            elif "FAIL: answer did not match" in verif:
                failures["Calculation/Extraction Error"].append(uid)
            else:
                failures["Other Failure"].append(uid)

for mode, uids in failures.items():
    print(f"Mode: {mode}")
    print(f"  UIDs: {', '.join(uids[:10])}...")

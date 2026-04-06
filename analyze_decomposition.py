import json
import re

def analyze():
    with open("decomposition_results_v3.json", "r") as f:
        data = json.load(f)

    total = len(data)
    failed = 0
    issues = []

    for item in data:
        qid = item.get("id")
        qtext = item.get("question", "")
        
        if "error" in item:
            failed += 1
            continue
            
        result = item.get("result")
        if not result:
            continue
            
        ptype = result.get("period_type")
        vformat = result.get("value_format")
        comp = result.get("computation")
        
        has_issue = False
        item_issues = []
        
        # CY + annual_total issue (only if asking for total/sum)
        if ptype == "calendar" and vformat == "annual_total" and re.search(r"total|sum", qtext, re.I):
            has_issue = True
            item_issues.append("CY_annual_total_mismatch")
            
        # Total/Sum + direct issue
        if re.search(r"total|sum", qtext, re.I) and comp == "direct":
            has_issue = True
            item_issues.append("sum_direct_mismatch")
            
        # Regression + direct issue
        if re.search(r"regression|ols|linreg", qtext, re.I) and comp == "direct":
            has_issue = True
            item_issues.append("regression_direct_mismatch")
            
        # Calendar year question + fiscal tag
        if re.search(r"calendar year", qtext, re.I) and ptype == "fiscal":
            has_issue = True
            item_issues.append("calendar_question_fiscal_tag")
            
        # Fiscal year question + calendar tag
        if re.search(r"fiscal year|fy", qtext, re.I) and ptype == "calendar":
            has_issue = True
            item_issues.append("fiscal_question_calendar_tag")
            
        # Empty years_needed
        if not result.get("years_needed"):
            has_issue = True
            item_issues.append("empty_years_needed")
            
        # Empty search_terms
        if not result.get("search_terms"):
            has_issue = True
            item_issues.append("empty_search_terms")

        if has_issue:
            issues.append({
                "id": qid,
                "question": qtext,
                "issues": item_issues,
                "result": result
            })

    print(f"Total: {total}")
    print(f"Failed: {failed}")
    print(f"Questions with issues: {len(issues)}")
    
    # Break down issues
    issue_counts = {}
    issue_ids = {}
    for item in issues:
        for iss in item["issues"]:
            issue_counts[iss] = issue_counts.get(iss, 0) + 1
            if iss not in issue_ids:
                issue_ids[iss] = []
            issue_ids[iss].append(item["id"])
            
    print("\nIssue breakdown:")
    for iss, count in issue_counts.items():
        print(f"  {iss}: {count} (IDs: {issue_ids[iss][:10]}{'...' if len(issue_ids[iss]) > 10 else ''})")

if __name__ == "__main__":
    analyze()

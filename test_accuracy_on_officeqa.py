"""Test pipeline accuracy on real OfficeQA questions with ground truth."""

import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, '.')

from file_locator import FileLocator
from table_finder import TableFinder
from data_normalizer import DataNormalizer
from column_finder import ColumnFinder
from row_finder import RowFinder
from value_parser import ValueParser


class OfficeQAAccuracyTester:
    """Test extraction pipeline on OfficeQA questions."""

    def __init__(self):
        self.file_locator = FileLocator()
        self.table_finder = TableFinder()
        self.normalizer = DataNormalizer()
        self.column_finder = ColumnFinder()
        self.row_finder = RowFinder()
        self.value_parser = ValueParser()

    def load_officeqa_data(self, csv_path: str, sample_size: int = None):
        """Load OfficeQA questions and ground truth."""
        questions = []
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                questions.append({
                    'uid': row.get('uid'),
                    'question': row.get('question'),
                    'ground_truth': row.get('answer'),
                    'source_files': row.get('source_files', ''),
                    'difficulty': row.get('difficulty', 'unknown')
                })

        if sample_size:
            questions = random.sample(questions, min(sample_size, len(questions)))

        return questions

    def test_question(self, question_data: dict, verbose: bool = False) -> dict:
        """Test extraction on a single question."""
        result = {
            'uid': question_data['uid'],
            'question': question_data['question'],
            'ground_truth': question_data['ground_truth'],
            'extracted_value': None,
            'success': False,
            'accuracy': 0.0,
            'errors': []
        }

        try:
            # Extract year from question (simple heuristic)
            import re
            year_match = re.search(r'(19|20)\d{2}', question_data['question'])
            if not year_match:
                result['errors'].append("Could not find year in question")
                return result

            year = int(year_match.group(0))

            # Try to find file
            file_path, file_meta = self.file_locator.locate_file(year=year)
            if file_path is None and file_meta.get('candidates'):
                file_path = file_meta['candidates'][0]

            if not file_path:
                result['errors'].append(f"No file found for year {year}")
                return result

            # Try to find table (heuristic: look for FFO)
            table_content, table_meta = self.table_finder.find_table(file_path, "FFO")
            if not table_content:
                result['errors'].append("Could not find FFO table")
                return result

            # Extract and normalize rows
            rows = self.table_finder.extract_rows(table_content)
            cleaned_rows, norm_meta = self.normalizer.clean_rows(rows)

            if not cleaned_rows:
                result['errors'].append("No rows in table")
                return result

            # Try to find matching column (look for receipts/expenditures)
            for col_term in ['total receipts', 'total expenditures', 'receipts', 'expenditures', 'total']:
                col_name, col_conf = self.column_finder.find_column(cleaned_rows, col_term)
                if col_name and col_conf > 0.60:
                    break

            if not col_name:
                result['errors'].append("Could not find matching column")
                return result

            # Try to find matching row
            row, row_idx, row_conf = self.row_finder.find_row_by_period(cleaned_rows, year=year)
            if not row:
                result['errors'].append(f"Could not find row for year {year}")
                return result

            # Extract value
            value_result = self.value_parser.extract_value(row, col_name)
            if value_result['value'] is None:
                result['errors'].append("Could not extract value")
                return result

            result['extracted_value'] = value_result['value']
            result['success'] = True

            # Check accuracy (simple string match after cleaning)
            ground_truth_clean = str(question_data['ground_truth']).replace(',', '').strip()
            extracted_clean = str(int(result['extracted_value'])) if isinstance(result['extracted_value'], float) else str(result['extracted_value']).replace(',', '')

            if ground_truth_clean == extracted_clean:
                result['accuracy'] = 1.0
            else:
                result['accuracy'] = 0.0

        except Exception as e:
            result['errors'].append(f"Exception: {str(e)}")

        return result

    def run_test(self, csv_path: str, sample_size: int = 10, verbose: bool = False) -> dict:
        """Run accuracy test on sample of OfficeQA questions."""
        print(f"\n{'=' * 70}")
        print(f"OFFICEQA ACCURACY TEST ({sample_size} questions)")
        print(f"{'=' * 70}\n")

        questions = self.load_officeqa_data(csv_path, sample_size)
        results = []
        passed = 0
        failed = 0

        for i, q in enumerate(questions, 1):
            print(f"Q{i}/{sample_size}: {q['question'][:70]}...")
            result = self.test_question(q, verbose=verbose)
            results.append(result)

            if result['success']:
                if result['accuracy'] == 1.0:
                    print(f"  ✅ CORRECT: {result['extracted_value']} (ground truth: {result['ground_truth']})")
                    passed += 1
                else:
                    print(f"  ⚠️  CLOSE: {result['extracted_value']} (ground truth: {result['ground_truth']})")
                    failed += 1
            else:
                print(f"  ❌ FAILED: {result['errors'][0]}")
                failed += 1

        accuracy = passed / max(1, passed + failed)

        print(f"\n{'=' * 70}")
        print(f"RESULTS: {passed} correct, {failed} failed")
        print(f"Accuracy: {accuracy * 100:.1f}%")
        print(f"{'=' * 70}\n")

        return {
            'accuracy': accuracy,
            'passed': passed,
            'failed': failed,
            'total': len(results),
            'results': results
        }


if __name__ == '__main__':
    csv_path = '/Users/jwalinshah/projects/officeqa-arena/data/officeqa_full.csv'

    tester = OfficeQAAccuracyTester()
    results = tester.run_test(csv_path, sample_size=5, verbose=False)

    print(f"\nSample Results:")
    for r in results['results'][:3]:
        print(f"  {r['uid']}: {'✅' if r['accuracy'] == 1.0 else '❌'} {r['question'][:50]}...")

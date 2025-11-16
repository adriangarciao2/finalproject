import json
import sys
from pathlib import Path

# Ensure project root is on sys.path so `mcp_tools` can be imported
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from mcp_tools import tests
from mcp_tools import dashboard


def main():
    print(f"Project root: {root}")

    print('\n=== analyze_java_sources() ===')
    class_infos = tests.analyze_java_sources(str(root))
    print(json.dumps(class_infos, indent=2))

    print('\n=== generate_junit_tests() ===')
    created = tests.generate_junit_tests(class_infos, str(root))
    print('Created test files:')
    for p in created:
        print(' -', p)

    print('\n=== run_maven_tests() ===')
    result = tests.run_maven_tests(str(root))
    # Print a summarized result to avoid huge logs
    summary = {k: result[k] for k in ('success', 'return_code', 'failed_tests')}
    print('Summary:', json.dumps(summary, indent=2))
    print('\nRaw output (first 400 chars):')
    print(result.get('raw_output', '')[:400])

    print('\n=== generate_coverage_dashboard() ===')
    md = dashboard.generate_coverage_dashboard(module='d2l', repo_root=str(root))
    print('Appended coverage report to', md)


if __name__ == '__main__':
    main()

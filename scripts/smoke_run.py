import json
import sys
import compileall
from pathlib import Path

# Ensure project root is on sys.path so mcp_tools can be imported when running from scripts/
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

print('Compiling mcp_tools...')
compileall.compile_dir('mcp_tools', force=True)

try:
    from mcp_tools import git_tools, coverage, tests
except Exception as e:
    print('Import failed:', e)
    raise

def run():
    print('\nRunning git_status()')
    st = git_tools.git_status('.')
    print(json.dumps({'branch': st.get('branch'), 'clean': st.get('clean')}, indent=2))

    # Parse existing jacoco report if present
    rp = Path('target') / 'site' / 'jacoco' / 'jacoco.xml'
    if rp.exists():
        print('\nParsing jacoco report...')
        parsed = coverage.parse_jacoco_report(str(rp))
        print('Overall counters:', ','.join(parsed.get('overall', {}).keys()))
        uc = coverage.find_uncovered_segments(str(rp))
        print('Uncovered segments:', len(uc))
        recs = coverage.coverage_recommendations(uc)
        if recs:
            print('Sample recommendation:', recs[0])
    else:
        print('\nNo jacoco.xml found; skipping coverage parse')

    print('\nRunning analyze_java_sources()')
    ai = tests.analyze_java_sources('.')
    print('Classes found:', len(ai))

    print('\nSmoke run completed successfully')

if __name__ == '__main__':
    run()

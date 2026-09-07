import sys
sys.path.insert(0, r'M:\Documents\Programming\Python\freqtrade\user_data\scripts')
import server
print('Import OK')
specs = server.LabHandler(None, None, None)._indicator_specs()
print('Total specs:', len(specs))
# Check a few
for name in ['wavetrend', 'vqzl_zscore', 'bbwp', 'cdl_engulfing']:
    spec = specs.get(name, {})
    print(f'{name}: title={spec.get("title")}, inputs={spec.get("inputs")}, params_count={len(spec.get("params", []))}')
    for p in spec.get('params', []):
        print(f'  param: {p}')
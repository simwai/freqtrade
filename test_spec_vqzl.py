import sys
sys.path.insert(0, r'M:\Documents\Programming\Python\freqtrade\user_data\scripts')
sys.path.insert(0, r'M:\Documents\Programming\Python\freqtrade\user_data\strategies\components')

# Force fresh import
if 'server' in sys.modules:
    del sys.modules['server']
if 'indicators_pandas_ta' in sys.modules:
    del sys.modules['indicators_pandas_ta']

import server
import indicators_pandas_ta as mod

# Check what the spec looks like
class TestHandler(server.LabHandler):
    pass

# Use a simple instance method to test
import inspect

# Build spec manually using the same code as _indicator_specs
_INDICATOR_COLUMNS = server.LabHandler._INDICATOR_COLUMNS
_INDICATOR_PRICE_SCALE = server.LabHandler._INDICATOR_PRICE_SCALE

# Build spec for vqzl_zscore
fn = getattr(mod, 'vqzl_zscore')
sig = inspect.signature(fn)
inputs = []
for p in sig.parameters.values():
    print(f'  param: {p.name}, default: {p.default}')
    if p.default is p.empty:
        col = _INDICATOR_COLUMNS.get(p.name)
        print(f'    -> col: {col}')
        if col is None:
            print('    -> SKIP (no col)')
            continue
        inputs.append((p.name, col))
    else:
        print(f'    -> SKIP (has default)')

print(f'inputs: {inputs}')
import sys
sys.path.insert(0, r'M:\Documents\Programming\Python\freqtrade\user_data\scripts')
sys.path.insert(0, r'M:\Documents\Programming\Python\freqtrade\user_data\strategies\components')

# Force the indicator module to load
import indicators_pandas_ta as mod
import server

# Now check the spec
class TestHandler(server.LabHandler):
    pass

# Just import to trigger module load
print('Module loaded')

# Check the spec for vqzl_zscore
import inspect
specs = server._INDICATOR_MODULE  # Check if module is accessible
fn = getattr(specs, 'vqzl_zscore')
sig = inspect.signature(fn)
print('vqzl_zscore params:')
for p in sig.parameters.values():
    print(f'  {p.name}, default={p.default}, annotation={p.annotation}')

# Check if the _coerce_param_value is in scope
print('_coerce_param_value exists:', hasattr(server, '_coerce_param_value'))
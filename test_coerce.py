import sys
sys.path.insert(0, r'M:\Documents\Programming\Python\freqtrade\user_data\scripts')
sys.path.insert(0, r'M:\Documents\Programming\Python\freqtrade\user_data\strategies\components')

# Test the _coerce_param_value function
from server import _coerce_param_value
import inspect

def test_coerce():
    # Test int annotation
    int_param = inspect.Parameter('n1', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int, default=10)
    result = _coerce_param_value('25', int_param.annotation)
    print(f'int 25: {result} (type: {type(result).__name__})')
    assert result == 25

    # Test float annotation
    float_param = inspect.Parameter('mult', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=float, default=2.0)
    result = _coerce_param_value('3.5', float_param.annotation)
    print(f'float 3.5: {result} (type: {type(result).__name__})')
    assert result == 3.5

    # Test no annotation
    result = _coerce_param_value('hello', inspect.Parameter.empty)
    print(f'no annotation "hello": {result} (type: {type(result).__name__})')
    assert result == 'hello'

    # Test invalid value for int
    try:
        result = _coerce_param_value('abc', int_param.annotation)
        print(f'invalid int "abc": {result}')
    except Exception as e:
        print(f'invalid int "abc": raised {e}')

    print('All tests passed!')

test_coerce()
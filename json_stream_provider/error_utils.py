import traceback
from typing import Dict, Tuple

from nbclient.exceptions import CellExecutionError
from nbformat.reader import NotJSONError


def prepare_response_error(error: Exception) -> Tuple[str, Dict[str, any]]:
    details: Dict[str, any] = resolve_cause({}, error)
    details['traceback'] = traceback.format_exception(type(error), error, error.__traceback__)

    if isinstance(error, CellExecutionError):
        details['details'] = error.traceback.split('\n')
        return f"Notebook execution failed: {error.ename}: {error.evalue}", details
    elif isinstance(error, NotJSONError):
        return f"Notebook read failed: {type(error).__name__}: {error}", details
    else:
        return f"{type(error).__name__}: {error}", details


def resolve_cause(accumulator: Dict[str, any], error: BaseException) -> Dict[str, any]:
    if error.__cause__:
        cause = error.__cause__
        cause_accumulator: Dict[str, any] = {
            'error': f"{type(cause).__name__}: {cause}"
        }
        accumulator['cause'] = resolve_cause(cause_accumulator, cause)
    return accumulator

#  Copyright 2025 Exactpro (Exactpro Systems Limited)
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

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

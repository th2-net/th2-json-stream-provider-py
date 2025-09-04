#  Copyright 2024-2025 Exactpro (Exactpro Systems Limited)
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
import logging
import re

from papermill.models import Parameter
from papermill.translators import PythonTranslator, papermill_translators

class CustomPythonTranslator(PythonTranslator):
    # Pattern to capture parameters within cell input
    PARAMETER_PATTERN = re.compile(
        r"^(?P<target>\w[\w_]*)\s*(:\s*[\"']?(?P<annotation>\w[\w_\[\],\s]*)[\"']?\s*)?=\s*(?P<value>(\"\"\"(?:\\.|[^\\])*?\"\"\"|\'\'\'(?:\\.|[^\\])*?\'\'\'|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\#]*?))(\s*#\s*(type:\s*(?P<type_comment>[^\s]*)\s*)?(?P<help>.*))?$"
    )
    logger: logging.Logger

    @classmethod
    def create_logger(cls):
        cls.logger = logging.getLogger('translator')

    # The code of this method is derived from https://github.com/nteract/papermill/blob/2.6.0 under the BSD License.
    # Original license follows:
    #
    # BSD 3-Clause License
    #
    # Copyright (c) 2017, nteract
    # All rights reserved.
    #
    # Redistribution and use in source and binary forms, with or without
    # modification, are permitted provided that the following conditions are met:
    #
    # * Redistributions of source code must retain the above copyright notice, this
    #   list of conditions and the following disclaimer.
    #
    # * Redistributions in binary form must reproduce the above copyright notice,
    #   this list of conditions and the following disclaimer in the documentation
    #   and/or other materials provided with the distribution.
    #
    # * Neither the name of the copyright holder nor the names of its
    #   contributors may be used to endorse or promote products derived from
    #   this software without specific prior written permission.
    #
    # THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
    # AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
    # IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
    # DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
    # FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
    # DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
    # SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
    # CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
    # OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
    # OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
    #
    # Modified by Exactpro for https://github.com/th2-net/th2-json-stream-provider-py
    @classmethod
    def inspect(cls, parameters_cell):
        """Inspect the parameters cell to get a Parameter list

                It must return an empty list if no parameters are found and
                it should ignore inspection errors.

                Parameters
                ----------
                parameters_cell : NotebookNode
                    Cell tagged _parameters_

                Returns
                -------
                List[Parameter]
                    A list of all parameters
                """
        params = []
        src = parameters_cell['source']

        def flatten_accumulator(accumulator):
            """Flatten a multilines variable definition.

            Remove all comments except on the latest line - will be interpreted as help.

            Args:
                accumulator (List[str]): Line composing the variable definition
            Returns:
                Flatten definition
            """
            flat_string = ""
            for line in accumulator[:-1]:
                if "#" in line:
                    comment_pos = line.index("#")
                    flat_string += line[:comment_pos].strip()
                else:
                    flat_string += line.strip()
            if len(accumulator):
                flat_string += accumulator[-1].strip()
            return flat_string

        # Some common type like dictionaries or list can be expressed over multiline.
        # To support the parsing of such case, the cell lines are grouped between line
        # actually containing an assignment. In each group, the commented and empty lines
        # are skip; i.e. the parameter help can only be given as comment on the last variable
        # line definition
        grouped_variable = []
        accumulator = []
        for iline, line in enumerate(src.splitlines()):
            if len(line.strip()) == 0 or line.strip().startswith('#'):
                continue  # Skip blank and comment

            nequal = line.count("=")
            if nequal > 0:
                grouped_variable.append(flatten_accumulator(accumulator))
                accumulator = []

            accumulator.append(line)
        grouped_variable.append(flatten_accumulator(accumulator))

        for definition in grouped_variable:
            if len(definition) == 0:
                continue

            match = re.match(cls.PARAMETER_PATTERN, definition)
            if match is not None:
                attr = match.groupdict()
                if attr["target"] is None:  # Fail to get variable name
                    cls.logger.debug("The %s definition doesn't contain 'target'", definition)
                    continue

                type_name = str(attr["annotation"] or attr["type_comment"] or None)
                parameter = Parameter(name=attr["target"].strip(), inferred_type_name=type_name.strip(),
                                      default=str(attr["value"]).strip(), help=str(attr["help"] or "").strip(), )
                params.append(parameter)

                cls.logger.debug("The %s parameter is parsed from %s definition", parameter, definition)
            else:
                cls.logger.debug("The %s definition isn't matched to the expression pattern", definition)


        return params

papermill_translators.register("python", CustomPythonTranslator)
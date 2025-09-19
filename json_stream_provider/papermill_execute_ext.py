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
from logging import INFO
from pathlib import Path


from papermill.log import logger
from papermill.execute import prepare_notebook_metadata, remove_error_markers, raise_for_execution_errors
from papermill.inspection import _infer_parameters
from papermill.iorw import get_pretty_path, load_notebook_node, local_file_io_cwd, write_ipynb
from papermill.parameterize import add_builtin_parameters, parameterize_notebook, parameterize_path
from papermill.utils import chdir

from json_stream_provider.custom_engines import exactpro_papermill_engines, DEFAULT_ENGINE_USER_ID


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
async def async_execute_notebook(
    input_path,
    output_path,
    engine_user_id=DEFAULT_ENGINE_USER_ID,
    parameters=None,
    engine_name=None,
    request_save_on_cell_execute=True,
    prepare_only=False,
    kernel_name=None,
    language=None,
    progress_bar=True,
    log_output=False,
    stdout_file=None,
    stderr_file=None,
    start_timeout=60,
    report_mode=False,
    cwd=None,
    **engine_kwargs,
):
    """Executes a single notebook locally.

    Parameters
    ----------
    input_path : str or Path or nbformat.NotebookNode
        Path to input notebook or NotebookNode object of notebook
    output_path : str or Path or None
        Path to save executed notebook. If None, no file will be saved
    engine_user_id : str
        User id to create papermill engine client
    parameters : dict, optional
        Arbitrary keyword arguments to pass to the notebook parameters
    engine_name : str, optional
        Name of execution engine to use
    request_save_on_cell_execute : bool, optional
        Request save notebook after each cell execution
    autosave_cell_every : int, optional
        How often in seconds to save in the middle of long cell executions
    prepare_only : bool, optional
        Flag to determine if execution should occur or not
    kernel_name : str, optional
        Name of kernel to execute the notebook against
    language : str, optional
        Programming language of the notebook
    progress_bar : bool, optional
        Flag for whether or not to show the progress bar.
    log_output : bool, optional
        Flag for whether or not to write notebook output to the configured logger
    start_timeout : int, optional
        Duration in seconds to wait for kernel start-up
    report_mode : bool, optional
        Flag for whether or not to hide input.
    cwd : str or Path, optional
        Working directory to use when executing the notebook
    **kwargs
        Arbitrary keyword arguments to pass to the notebook engine

    Returns
    -------
    nb : NotebookNode
       Executed notebook object
    """
    if isinstance(input_path, Path):
        input_path = str(input_path)
    if isinstance(output_path, Path):
        output_path = str(output_path)
    if isinstance(cwd, Path):
        cwd = str(cwd)

    path_parameters = add_builtin_parameters(parameters)
    input_path = parameterize_path(input_path, path_parameters)
    output_path = parameterize_path(output_path, path_parameters)

    if logger.isEnabledFor(INFO):
        logger.info(f"Input Notebook:  {get_pretty_path(input_path)}")
        logger.info(f"Output Notebook: {get_pretty_path(output_path)}")
    with local_file_io_cwd():
        if cwd is not None:
            if logger.isEnabledFor(INFO):
                logger.info(f"Working directory: {get_pretty_path(cwd)}")

        nb = load_notebook_node(input_path)

        # Parameterize the Notebook.
        if parameters:
            parameter_predefined = _infer_parameters(nb, name=kernel_name, language=language)
            parameter_predefined = {p.name for p in parameter_predefined}
            for p in parameters:
                if p not in parameter_predefined:
                    logger.warning('Passed unknown parameter: %s', p)
            nb = parameterize_notebook(
                nb,
                parameters,
                report_mode,
                kernel_name=kernel_name,
                language=language,
                engine_name=engine_name,
            )

        nb = prepare_notebook_metadata(nb, input_path, output_path, report_mode)
        # clear out any existing error markers from previous papermill runs
        nb = remove_error_markers(nb)

        if not prepare_only:
            # Dropdown to the engine to fetch the kernel name from the notebook document
            kernel_name = exactpro_papermill_engines.nb_kernel_name(engine_name=engine_name, nb=nb, name=kernel_name)
            # Execute the Notebook in `cwd` if it is set
            with chdir(cwd):
                nb = await exactpro_papermill_engines.async_execute_notebook_with_engine(
                    engine_name,
                    nb,
                    engine_user_id=engine_user_id,
                    input_path=input_path,
                    output_path=output_path if request_save_on_cell_execute else None,
                    kernel_name=kernel_name,
                    progress_bar=progress_bar,
                    log_output=log_output,
                    start_timeout=start_timeout,
                    stdout_file=stdout_file,
                    stderr_file=stderr_file,
                    **engine_kwargs,
                )

            # Check for errors first (it saves on error before raising)
            raise_for_execution_errors(nb, output_path)

        # Write final output in case the engine didn't write it on cell completion.
        write_ipynb(nb, output_path)

        return nb

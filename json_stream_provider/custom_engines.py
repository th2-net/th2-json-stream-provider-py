#  Copyright 2024 Exactpro (Exactpro Systems Limited)
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

import logging.config
import time
from datetime import datetime

from papermill.clientwrap import PapermillNotebookClient
from papermill.engines import NBClientEngine, NotebookExecutionManager, PapermillEngines
from papermill.utils import remove_args, merge_kwargs, logger

DEFAULT_ENGINE_USER_ID = 'default_engine_user_id'


class EngineKey:
    def __init__(self, user_id, notebook_file):
        self.user_id = user_id
        self.notebook_file = notebook_file

    def __hash__(self):
        # Combine attributes for a unique hash
        return hash((self.user_id, self.notebook_file))

    def __eq__(self, other):
        if isinstance(other, EngineKey):
            return self.user_id == other.user_id and self.notebook_file == other.notebook_file
        return False

    def __iter__(self):
        return iter((self.user_id, self.notebook_file))

    def __str__(self):
        return f"{self.user_id}:{self.notebook_file}"


class EngineHolder:
    _key: EngineKey
    _client: PapermillNotebookClient
    _last_used_time: float
    _busy: bool = False

    def __init__(self, key: EngineKey, client: PapermillNotebookClient):
        self._key = key
        self._client = client
        self._last_used_time = time.time()

    def __str__(self):
        return f"Engine(key={self._key}, last_used_time={self._last_used_time}, is_busy={self._busy})"

    async def async_execute(self, nb_man):
        if self._busy:
            raise EngineBusyError(
                f"Notebook client related to '{self._key}' has been busy since {self._get_last_used_date_time()}")

        try:
            self._busy = True
            # accept new notebook into (possibly) existing client
            self._client.nb_man = nb_man
            self._client.nb = nb_man.nb
            # reuse client connection to existing kernel
            output = await self._client.async_execute(cleanup_kc=False)
            # renumber executions
            for i, cell in enumerate(nb_man.nb.cells):
                if 'execution_count' in cell:
                    cell['execution_count'] = i + 1

            return output
        finally:
            self._busy = False

    def get_last_used_time(self) -> float:
        return self._last_used_time

    def close(self):
        self._client = None

    def _get_last_used_date_time(self):
        return datetime.fromtimestamp(self._last_used_time)


class EngineBusyError(RuntimeError):
    pass


class CustomEngine(NBClientEngine):
    out_of_use_engine_time: int = 60 * 60
    metadata_dict: dict = {}
    logger: logging.Logger

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
    async def async_execute_notebook(
            cls,
            nb,
            kernel_name,
            engine_user_id=DEFAULT_ENGINE_USER_ID,
            output_path=None,
            progress_bar=True,
            log_output=False,
            autosave_cell_every=30,
            **kwargs,
    ):
        """
        A wrapper to handle notebook execution tasks.

        Wraps the notebook object in a `NotebookExecutionManager` in order to track
        execution state in a uniform manner. This is meant to help simplify
        engine implementations. This allows a developer to just focus on
        iterating and executing the cell contents.
        """
        nb_man = NotebookExecutionManager(
            nb,
            output_path=output_path,
            progress_bar=progress_bar,
            log_output=log_output,
            autosave_cell_every=autosave_cell_every,
        )

        nb_man.notebook_start()
        try:
            await cls.async_execute_managed_notebook(nb_man, kernel_name, log_output=log_output,
                                                     engine_user_id=engine_user_id, **kwargs)
        finally:
            nb_man.cleanup_pbar()
            nb_man.notebook_complete()

        return nb_man.nb

    # this method has been copied from the issue comment
    # https://github.com/nteract/papermill/issues/583#issuecomment-791988091
    @classmethod
    async def async_execute_managed_notebook(
            cls,
            nb_man,
            kernel_name,
            engine_user_id=DEFAULT_ENGINE_USER_ID,
            log_output=False,
            stdout_file=None,
            stderr_file=None,
            start_timeout=60,
            execution_timeout=None,
            **kwargs
    ):
        """
        Performs the actual execution of the parameterized notebook locally.

        Args:
            nb_man (NotebookExecutionManager): Wrapper for execution state of a notebook.
            kernel_name (str): Name of kernel to execute the notebook against.
            log_output (bool): Flag for whether or not to write notebook output to the
                               configured logger.
            start_timeout (int): Duration to wait for kernel start-up.
            execution_timeout (int): Duration to wait before failing execution (default: never).
            engine_user_id (str): User id to create papermill engine client
        """

        key = EngineKey(engine_user_id, nb_man.nb['metadata']['papermill']['input_path'])

        def create_client():  # TODO: should be static
            # Exclude parameters that named differently downstream
            safe_kwargs = remove_args(['timeout', 'startup_timeout'], **kwargs)

            # Nicely handle preprocessor arguments prioritizing values set by engine
            final_kwargs = merge_kwargs(
                safe_kwargs,
                timeout=execution_timeout if execution_timeout else kwargs.get('timeout'),
                startup_timeout=start_timeout,
                kernel_name=kernel_name,
                log=logger,
                log_output=log_output,
                stdout_file=stdout_file,
                stderr_file=stderr_file,
            )
            cls.logger.info(f"Created papermill notebook client for {key}")
            return PapermillNotebookClient(nb_man, **final_kwargs)

        engine_holder: EngineHolder = cls.get_or_create_engine_metadata(key, create_client)
        return await engine_holder.async_execute(nb_man)

    @classmethod
    def create_logger(cls):
        cls.logger = logging.getLogger('engine')

    @classmethod
    def set_out_of_use_engine_time(cls, value: int):
        cls.out_of_use_engine_time = value

    @classmethod
    def get_or_create_engine_metadata(cls, key: EngineKey, func):
        cls.remove_out_of_date_engines(key)

        engine_holder: EngineHolder = cls.metadata_dict.get(key)
        if engine_holder is None:
            engine_holder = EngineHolder(key, func())
            cls.metadata_dict[key] = engine_holder

        return engine_holder

    @classmethod
    def remove_out_of_date_engines(cls, exclude_key: EngineKey):
        now = time.time()
        dead_line = now - cls.out_of_use_engine_time
        out_of_use_engines = [key for key, metadata in cls.metadata_dict.items() if
                              key != exclude_key and metadata.get_last_used_time() < dead_line]
        for key in out_of_use_engines:
            engine_holder: EngineHolder = cls.metadata_dict.pop(key)
            engine_holder.close()
            cls.logger.info(
                f"unregistered '{key}' papermill engine, last used time {now - engine_holder.get_last_used_time()} sec ago")


class CustomEngines(PapermillEngines):
    async def async_execute_notebook_with_engine(self, engine_name, nb, kernel_name,
                                                 engine_user_id=DEFAULT_ENGINE_USER_ID, **kwargs):
        """Fetch a named engine and execute the nb object against it."""
        return await self.get_engine(engine_name).async_execute_notebook(nb, kernel_name, engine_user_id, **kwargs)


# Instantiate a ExactproPapermillEngines instance, register Handlers and entrypoints
exactpro_papermill_engines = CustomEngines()
exactpro_papermill_engines.register(None, CustomEngine)
exactpro_papermill_engines.register_entry_points()

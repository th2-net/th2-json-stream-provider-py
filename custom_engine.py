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

import logging.config
import time

from papermill.clientwrap import PapermillNotebookClient
from papermill.engines import NBClientEngine
from papermill.utils import remove_args, merge_kwargs, logger


class MetadataKey:
    def __init__(self, client_id, notebook_file):
        self.client_id = client_id
        self.notebook_file = notebook_file

    def __hash__(self):
        # Combine attributes for a unique hash
        return hash((self.client_id, self.notebook_file))

    def __eq__(self, other):
        if isinstance(other, MetadataKey):
            return self.client_id == other.client_id and self.notebook_file == other.notebook_file
        return False

    def __iter__(self):
        return iter((self.client_id, self.notebook_file))

    def __str__(self):
        return f"{self.client_id}:{self.notebook_file}"


class EngineMetadata:
    client: PapermillNotebookClient = None
    last_used_time: float = time.time()


# this file has been copied from the issue comment
# https://github.com/nteract/papermill/issues/583#issuecomment-791988091
class CustomEngine(NBClientEngine):
    out_of_use_engine_time: int = 60 * 60
    metadata_dict: dict = {}
    logger: logging.Logger

    @classmethod
    def renumber_executions(cls, nb):
        for i, cell in enumerate(nb.cells):
            if 'execution_count' in cell:
                cell['execution_count'] = i + 1

    @classmethod
    def execute_managed_notebook(
            cls,
            nb_man,
            kernel_name,
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
        """

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
        # TODO: pass client_id
        key = MetadataKey("", nb_man.nb['metadata']['papermill']['input_path'])
        metadata = cls.get_engine_metadata(key)
        if metadata.client is None:
            metadata.client = PapermillNotebookClient(nb_man, **final_kwargs)
            cls.logger.info(f"Created papermill notebook client for {key}")

        # accept new notebook into (possibly) existing client
        metadata.client.nb_man = nb_man
        metadata.client.nb = nb_man.nb
        # reuse client connection to existing kernel
        output = metadata.client.execute(cleanup_kc=False)
        cls.renumber_executions(nb_man.nb)

        return output

    @classmethod
    def create_logger(cls):
        cls.logger = logging.getLogger('engine')

    @classmethod
    def set_out_of_use_engine_time(cls, value: int):
        cls.out_of_use_engine_time = value

    @classmethod
    def get_engine_metadata(cls, key: MetadataKey):
        cls.remove_out_of_date_engines(key)
        metadata: EngineMetadata
        if key not in cls.metadata_dict:
            metadata = EngineMetadata()
            cls.metadata_dict[key] = metadata
        else:
            metadata = cls.metadata_dict[key]
        return metadata

    @classmethod
    def remove_out_of_date_engines(cls, exclude_key: MetadataKey):
        now = time.time()
        dead_line = now - cls.out_of_use_engine_time
        out_of_use_engines = [key for key, metadata in cls.metadata_dict.items() if
                              key != exclude_key and metadata.last_used_time < dead_line]
        for key in out_of_use_engines:
            metadata: EngineMetadata = cls.metadata_dict.pop(key)
            metadata.client = None
            cls.logger.info(
                f"Unregistered '{key}' papermill engine, last used time {now - metadata.last_used_time} sec ago")

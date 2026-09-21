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
import os

# /var/th2/config is where th2 components get all of their configuration inside a container
default_config_dir = '/var/th2/config'
log4py_file_name = 'log4py.conf'
log4py_file = os.path.join(default_config_dir, log4py_file_name)


def resolve_log4py_file(config_dir: str = None) -> str:
    """The logging configuration lives next to the custom configuration it belongs to."""
    if config_dir:
        return os.path.join(config_dir, log4py_file_name)
    return log4py_file


def configure_logging(config_dir: str = None):
    configured_file = resolve_log4py_file(config_dir)
    if os.path.exists(configured_file):
        logging.config.fileConfig(configured_file, disable_existing_loggers=False)
        logging.getLogger(__name__).info(f'Logger is configured by {configured_file} file')
    else:
        default_logging_config = {
            'version': 1,
            # logging is configured after the module loggers are created, disabling them here
            # would silence every logger the application already holds
            'disable_existing_loggers': False,
            'formatters': {
                'default': {
                    'format': '%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s',
                    'datefmt': '%Y-%m-%d %H:%M:%S'
                },
            },
            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'default',
                    'level': 'DEBUG',
                    'stream': 'ext://sys.stdout'
                },
            },
            'root': {
                'handlers': ['console'],
                'level': 'DEBUG',
            },
        }
        logging.config.dictConfig(default_logging_config)
        logging.getLogger(__name__).info('Logger is configured by default')

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

log4py_file = '/var/th2/config/log4py.conf'


def configure_logging():
    if os.path.exists(log4py_file):
        logging.config.fileConfig(log4py_file, disable_existing_loggers=False)
        logging.getLogger(__name__).info(f'Logger is configured by {log4py_file} file')
    else:
        default_logging_config = {
            'version': 1,
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

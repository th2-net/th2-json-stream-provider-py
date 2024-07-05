import logging.config
import os

log4py_file = '/var/th2/config/log4py.conf'
def configureLogging():
    if os.path.exists(log4py_file):
        logging.config.fileConfig(log4py_file, disable_existing_loggers=False)
        logging.getLogger(__name__).info(f'Logger is configured by {log4py_file} file')
    else:
        default_logging_config = {
            'version': 1,
            'formatters': {
                'default': {
                    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
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



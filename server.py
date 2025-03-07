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

import asyncio
import json
import logging.config
import os
from argparse import ArgumentParser
from asyncio import Task
from datetime import datetime, timezone
from enum import Enum
from logging import INFO
from typing import Coroutine, Any
from uuid import uuid4

import papermill as pm
from aiohttp import web
from aiohttp.web_middlewares import middleware
from aiohttp.web_request import Request
from aiohttp.web_response import Response
from aiohttp_swagger import *
from aiojobs import Job
from aiojobs.aiohttp import setup
from papermill.utils import chdir

from json_stream_provider import papermill_execute_ext as epm
from json_stream_provider.custom_engines import CustomEngine, EngineBusyError
from json_stream_provider.custom_python_translator import CustomPythonTranslator
from json_stream_provider.log_configuratior import configure_logging
from json_stream_provider.papermill_execute_ext import DEFAULT_ENGINE_USER_ID

ENGINE_USER_ID_COOKIE_KEY = 'engine_user_id'

os.system('pip list')

server_status: str = 'ok'
notebooks_dir: str = '/home/jupyter-notebook/'
results_dir: str = '/home/jupyter-notebook/results/'
log_dir: str = '/home/jupyter-notebook/logs/'

tasks: dict = {}

configure_logging()
CustomEngine.create_logger()
CustomPythonTranslator.create_logger()
logger: logging.Logger = logging.getLogger('j-sp')


class TaskStatus(Enum):
    CREATED = 'created'
    SUCCESS = 'success'
    FAILED = 'failed'
    IN_PROGRESS = 'in progress'


class TaskMetadata:
    task_id: str
    task: Task[None]
    status: TaskStatus
    result: Any
    customization: str = ''
    job: Coroutine[Any, Any, Job[None]] = None

    def __init__(self, task_id: str, result: Any = '', customization: str = '',
                 job: Coroutine[Any, Any, Job[None]] = None):
        self.task_id = task_id
        self.status = TaskStatus.CREATED
        self.result = result
        self.customization = customization
        self.job = job

    def close_job(self) -> None:
        if self.job is not None:
            self.job.close()


def create_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path)


def read_config(path: str):
    global notebooks_dir
    global results_dir
    global log_dir
    global logger
    try:
        file = open(path, "r")
        cfg = json.load(file)

        notebooks_dir = os.path.abspath(cfg.get('notebooks', notebooks_dir))
        logger.info('notebooks_dir=%s', notebooks_dir)
        if notebooks_dir:
            create_dir(notebooks_dir)

        results_dir = os.path.abspath(cfg.get('results', results_dir))
        logger.info('results_dir=%s', results_dir)
        if results_dir:
            create_dir(results_dir)

        log_dir = os.path.abspath(cfg.get('logs', log_dir))
        logger.info('log_dir=%s', log_dir)
        if log_dir:
            create_dir(log_dir)

        CustomEngine.set_out_of_use_engine_time(cfg.get('out-of-use-engine-time', CustomEngine.out_of_use_engine_time))
    except Exception as e:
        logger.error(f"Read '{path}' configuration failure", e)


def get_or_default_engine_user_id(req: Request) -> str:
    return req.cookies.get(ENGINE_USER_ID_COOKIE_KEY, DEFAULT_ENGINE_USER_ID)


def get_or_gen_engine_user_id(req: Request = None) -> str:
    global logger

    engine_user_id: str = DEFAULT_ENGINE_USER_ID
    if req is not None:
        engine_user_id = get_or_default_engine_user_id(req)
    if engine_user_id == DEFAULT_ENGINE_USER_ID:
        engine_user_id = str(uuid4())
        if logger.isEnabledFor(INFO):
            user_agent = req.headers.get('User-Agent', 'unknown')
            user_ip = req.remote
            logger.info(f"Generated user identifier for {user_ip}/{user_agent}")
    return engine_user_id


def put_engine_user_id_if_absent(res: Response, engine_user_id: str = None, req: Request = None) -> Response:
    if res.cookies.get(ENGINE_USER_ID_COOKIE_KEY) is not None:
        return res

    if engine_user_id is None:
        engine_user_id = get_or_gen_engine_user_id(req)
    res.set_cookie(ENGINE_USER_ID_COOKIE_KEY, engine_user_id)
    return res


@middleware
async def add_engine_user_id_middleware(req, handler):
    res = await handler(req)
    if isinstance(req, Request) and isinstance(res, Response) and res.status == 200:
        res = put_engine_user_id_if_absent(res=res, req=req)
    return res


# noinspection PyUnusedLocal
async def req_status(req: Request) -> Response:
    """
    ---
    description: This end-point allow to test that service is up.
    tags:
    - Health check
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return json with server status
    """
    global server_status
    return web.json_response({'status': server_status})


def get_dirs(path):
    return [f.path for f in os.scandir(path) if f.is_dir() and f.name[0] != '.']


def get_files(path, file_type):
    return [f.path for f in os.scandir(path) if f.is_file() and f.name.endswith(file_type) and f.name[0] != '.']


def replace_slashes(path: str):
    return path.replace('\\', '/')


def verify_path(path: str, trusted: set[str]) -> str:
    absolute_path = os.path.abspath(path)
    for trusted_dir in trusted:
        if trusted_dir in absolute_path:
            return absolute_path
    raise ValueError(f"Verified '{absolute_path}'({path}) path isn't a part of {trusted} trusted paths")

async def req_notebooks(req: Request) -> Response:
    """
    ---
    description: This end-point allows to get notebooks that could be requested.
      Query requires path to directory in which notebooks is searched.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return dictionary of available directories/files.
        "404":
            description: failed operation when queried directory doesn't exist
              or requested path didn't start with ./notebooks.
    """
    global logger
    path_arg = req.rel_url.query.get('path', '')
    logger.info('/files/notebooks?path={path}'.format(path=str(path_arg)))
    if path_arg == '':
        dirs = []
        if os.path.isdir(notebooks_dir):
            dirs = list(get_dirs(notebooks_dir))
        files = list(get_files(notebooks_dir, '.ipynb'))

        dirs.sort()
        files.sort()

        return web.json_response({
            'directories': dirs,
            'files': files
        })

    try:
        absolute_path = verify_path(path_arg, {notebooks_dir})
    except Exception as error:
        logger.warning(f"Requested {path_arg} path didn't start with {notebooks_dir}", error)
        return web.HTTPNotFound(reason=f"Requested {path_arg} path didn't start with {notebooks_dir}")

    if path_arg:
        if os.path.isdir(absolute_path):
            dirs = list(get_dirs(absolute_path))
            files = list(get_files(absolute_path, '.ipynb'))

            dirs.sort()
            files.sort()

            return web.json_response({
                'directories': dirs,
                'files': files
            })
        else:
            return web.HTTPNotFound()

    return web.json_response({
        'directories': [],
        'files': []
    })


async def req_jsons(req: Request) -> Response:
    """
    ---
    description: This end-point allows to get JSONLs that could be requested.
      Query requires path to directory in which JSONLs is searched.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return dictionary of available directories/files.
        "404":
            description: failed operation when queried directory doesn't exist
              or requested path didn't start with ./results or ./notebooks.
    """
    global logger
    path_arg = req.rel_url.query.get('path', '')
    logger.info('/files/results?path={path}'.format(path=str(path_arg)))

    if path_arg == '':
        dirs_res = []
        dirs_note = []
        if os.path.isdir(results_dir):
            dirs_res = list(get_dirs(results_dir))

        if os.path.isdir(notebooks_dir):
            dirs_note = list(get_dirs(notebooks_dir))

        files_res = list(get_files(results_dir, '.jsonl'))
        files_note = list(get_files(notebooks_dir, '.jsonl'))

        dirs = list({*dirs_note, *dirs_res})
        files = list({*files_note, *files_res})

        dirs.sort()
        files.sort()

        return web.json_response({
            'directories': dirs,
            'files': files
        })

    try:
        absolute_path = verify_path(path_arg, {results_dir, notebooks_dir})
    except Exception as error:
        logger.warning(f"Requested {path_arg} path didn't start with {results_dir} or {notebooks_dir}", error)
        return web.HTTPNotFound(reason=f"Requested {path_arg} path didn't start with {results_dir} or {notebooks_dir}")

    if path_arg:
        if os.path.isdir(absolute_path):
            dirs = list(get_dirs(absolute_path))
            files = list(get_files(absolute_path, '.jsonl'))

            dirs.sort()
            files.sort()

            return web.json_response({
                'directories': dirs,
                'files': files
            })
        else:
            return web.HTTPNotFound()

    return web.json_response({
        'directories': [],
        'files': []
    })


async def req_files(req: Request) -> Response:
    """
    ---
    description: This end-point allows to get files and directories.
      Query requires path to directory in which files and directories is searched.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return dictionary of available directories/files.
        "404":
            description: failed operation when queried directory doesn't exist
              or requested path didn't start with ./results or ./notebooks.
    """
    global logger
    path_arg = req.rel_url.query.get('path', '')
    logger.info('/files/all?path={path}'.format(path=str(path_arg)))

    if path_arg == '':
        dirs_res = []
        dirs_note = []
        if os.path.isdir(results_dir):
            dirs_res = list(get_dirs(results_dir))

        if os.path.isdir(notebooks_dir):
            dirs_note = list(get_dirs(notebooks_dir))

        files_res = list(get_files(results_dir, ''))
        files_note = list(get_files(notebooks_dir, ''))

        dirs = list({*dirs_note, *dirs_res})
        files = list({*files_note, *files_res})

        dirs.sort()
        files.sort()

        return web.json_response({
            'directories': dirs,
            'files': files
        })

    try:
        absolute_path = verify_path(path_arg, {results_dir, notebooks_dir})
    except Exception as error:
        logger.warning(f"Requested {path_arg} path didn't start with {results_dir} or {notebooks_dir}", error)
        return web.HTTPNotFound(reason=f"Requested {path_arg} path didn't start with {results_dir} or {notebooks_dir}")

    if path_arg:
        if os.path.isdir(absolute_path):
            dirs = list(get_dirs(absolute_path))
            files = list(get_files(absolute_path, ''))

            dirs.sort()
            files.sort()

            return web.json_response({
                'directories': dirs,
                'files': files
            })
        else:
            return web.HTTPNotFound()

    return web.json_response({
        'directories': [],
        'files': []
    })


async def req_parameters(req: Request) -> Response:
    """
    ---
    description: This end-point allows to get parameters for notebook in requested path.
      Query requires path to notebook.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return json of file's parameters.
        "404":
            description: failed operation when queried file doesn't exist
              or requested path didn't start with ./notebooks.
    """
    global logger
    path_arg = req.rel_url.query.get('path', '')
    logger.info('/files?path={path}'.format(path=str(path_arg)))
    try:
        absolute_path = verify_path(path_arg, {notebooks_dir})
    except Exception as error:
        logger.warning(f"Requested {path_arg} path didn't start with {notebooks_dir}", error)
        return web.HTTPNotFound(reason=f"Requested {path_arg} path didn't start with {notebooks_dir}")
    if not path_arg or not os.path.isfile(absolute_path):
        return web.HTTPNotFound()
    params = pm.inspect_notebook(absolute_path)
    return web.json_response(params)


async def launch_notebook(engine_user_id: str, input_path, arguments: dict, file_name, task_metadata: TaskMetadata):
    global logger
    global tasks
    logger.info(f'launching notebook {input_path} with {arguments}')

    if task_metadata is None:
        return

    task_metadata.status = TaskStatus.IN_PROGRESS
    start_execution = datetime.now()
    log_out: str = (log_dir + '/%s.log.ipynb' % file_name) if log_dir and file_name else None
    try:
        with chdir(input_path[:input_path.rfind('/')]):
            input_path = input_path[input_path.rfind('/') + 1:]
            await epm.async_execute_notebook(
                engine_user_id=engine_user_id,
                input_path=input_path,
                output_path=log_out,
                parameters=arguments,
            )
            logger.debug(f'successfully launched notebook {input_path}')
            task_metadata.status = TaskStatus.SUCCESS
            task_metadata.result = arguments.get('output_path')
            task_metadata.customization = arguments.get('customization_path')
    except EngineBusyError as error:
        logger.warning(error.args)
        task_metadata.status = TaskStatus.FAILED
        task_metadata.result = error
    except Exception as error:
        logger.error(f'failed to launch notebook {input_path}', error)
        task_metadata.status = TaskStatus.FAILED
        task_metadata.result = error
    finally:
        spent_time = (datetime.now() - start_execution).total_seconds()
        logger.info(f'ended launch notebook {input_path} with {arguments} spent_time {spent_time} sec')


def verify_parameter(parameter):
    parameter_type = parameter.get('type')
    parameter_value = parameter.get('value')
    if parameter_type == 'file path':
        try:
            return verify_path(parameter_value, {notebooks_dir, results_dir})
        except Exception as error:
            msg = (f"Parameter {parameter.get('name')} of type={parameter_type} with value={parameter_value} "
                   f"didn't start with {notebooks_dir} or {results_dir}")
            logger.error(msg, error)
            raise Exception(msg, error)
    else:
        return parameter_value


async def req_launch(req: Request) -> Response:
    """
    ---
    description: This end-point allows to start notebook. Query requires path to notebook.
      Body required to be dictionary of parameters.
    tags:
    - Execution operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return json with path for resulting file.
        "400":
            description: failed operation. body with parameters not present.
        "404":
            description: failed operation. requested file doesn't exist or requested path didn't start with ./notebooks.
        "500":
            description: failed operation. directory for output doesn't exist.
    """
    global tasks
    global logger
    path_arg = req.rel_url.query.get('path', '')
    logger.info('/execute?path={path}'.format(path=str(path_arg)))
    if not req.can_read_body:
        return web.HTTPBadRequest(reason='Body with parameters not present')
    try:
        absolute_path = verify_path(path_arg, {notebooks_dir})
    except Exception as error:
        logger.warning(f"Requested {path_arg} path didn't start with {notebooks_dir}", error)
        return web.HTTPNotFound(reason=f"Requested {path_arg} path didn't start with {notebooks_dir}")
    if not path_arg or not os.path.isfile(absolute_path):
        return web.HTTPNotFound()
    if not os.path.exists(results_dir):
        return web.HTTPInternalServerError(reason='No output directory')
    notebook_name = absolute_path.split('/')[-1].split('.')[0]
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
    file_name = notebook_name + '_' + timestamp
    output_path = results_dir + '/%s.jsonl' % str(file_name)
    customization_path = results_dir + '/%s.json' % str(file_name)
    req_json = await req.json()
    user_id = get_or_default_engine_user_id(req)
    parameters = {}
    for key, parameter in req_json.items():
        try:
            parameters[key] = verify_parameter(parameter)
        except Exception as error:
            return web.HTTPInternalServerError(reason=str(error))
    parameters['output_path'] = output_path
    parameters['customization_path'] = customization_path
    task_id = str(uuid4())
    task_metadata = TaskMetadata(task_id=task_id)
    tasks[task_id] = task_metadata
    task: Task[None] = asyncio.create_task(
        launch_notebook(user_id, absolute_path, parameters, file_name, task_metadata))
    task_metadata.task = task
    return web.json_response({'task_id': task_id})


async def req_file(req: Request) -> Response:
    """
    ---
    description: This end-point allows to get file from requested path. Query requires path to file.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return file's json.
        "404":
            description: failed operation. requested file doesn't exist
              or requested path didn't start with ./results or ./notebooks.
    """
    global tasks
    global logger
    path_arg = req.rel_url.query.get('path', '')
    logger.info('/file?path={path}'.format(path=str(path_arg)))
    try:
        absolute_path = verify_path(path_arg, {results_dir, notebooks_dir})
    except Exception as error:
        logger.warning(f"Requested {path_arg} path didn't start with {results_dir} or {notebooks_dir}", error)
        return web.HTTPNotFound(reason=f"Requested {path_arg} path didn't start with {results_dir} or {notebooks_dir}")
    if not path_arg or not os.path.isfile(absolute_path):
        return web.HTTPNotFound()
    file = open(absolute_path, "r")
    content = file.read()
    file.close()
    return web.json_response({'result': content})


async def req_result(req: Request) -> Response:
    """
    ---
    description: This end-point allows to get result from requested task.
      Query requires task id from which result is required.
    tags:
    - Execution operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return different data depending on status:
                'in progress': return json with task's status
                'success': return json with result's content
                'error': return json with reason of failed run
        "400":
            description: failed operation. body with parameters not present.
        "404":
            description: failed operation. requested task doesn't exist
              or resulting file doesn't exist or status is unknown.
    """
    global tasks
    global logger
    task_id = req.rel_url.query.get('id')
    logger.debug('/result?id={task_id}'.format(task_id=str(task_id)))
    task: TaskMetadata = tasks.get(task_id)
    if task is None:
        return web.HTTPNotFound(reason="Requested task doesn't exist")
    status = task.status
    if status == TaskStatus.IN_PROGRESS:
        return web.json_response({'status': status.value})
    elif status == TaskStatus.SUCCESS:
        path_param = task.result
        if not path_param or not os.path.isfile(path_param):
            return web.HTTPNotFound(reason="Resulting file doesn't exist")
        customization_param = task.customization
        customization = "[]"
        if len(customization_param) > 0 and os.path.isfile(customization_param):
            customization_file = open(customization_param, "r")
            customization = customization_file.read()
            customization_file.close()
        file = open(path_param, "r")
        content = file.read()
        file.close()
        return web.json_response(
            {'status': status.value, 'result': content, 'customization': customization, 'path': path_param})
    elif status == TaskStatus.FAILED:
        error: Exception = task.result
        return web.json_response({'status': status.value, 'result': str(error)})
    else:
        return web.HTTPNotFound()


async def req_stop(req: Request) -> Response:
    """
    ---
    description: This end-point allows to stop task. Query requires task id which will be stopped.
    tags:
    - Execution operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return nothing.
        "500":
            description: failed operation. failed to stop process.
    """
    global tasks
    global logger
    task_id = req.rel_url.query.get('id')
    logger.info('/stop?id={task_id}'.format(task_id=str(task_id)))
    task: TaskMetadata = tasks.pop(task_id)
    try:
        if task and task.status == TaskStatus.IN_PROGRESS:
            task.task.cancel("stopped by user")
    except Exception as error:
        logger.warning("failed to stop process", error)
        return web.HTTPInternalServerError(reason='failed to stop process')
    return web.HTTPOk()


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('config')
    cfg_path = vars(parser.parse_args()).get('config')
    if cfg_path:
        read_config(cfg_path)

    app = web.Application(middlewares=[add_engine_user_id_middleware])

    setup(app)
    app.router.add_route('GET', "/status", req_status)
    app.router.add_route('GET', "/files/notebooks", req_notebooks)
    app.router.add_route('GET', "/files/results", req_jsons)
    app.router.add_route('GET', "/files/all", req_files)
    app.router.add_route('GET', "/files", req_parameters)
    app.router.add_route('GET', "/file", req_file)
    app.router.add_route('POST', "/execute", req_launch)
    app.router.add_route('GET', "/result", req_result)
    app.router.add_route('POST', "/stop", req_stop)
    setup_swagger(app)
    logger.info('starting server')
    web.run_app(app)

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
from datetime import datetime, timezone

import papermill as pm
from aiohttp import web
from aiohttp.web_request import Request
from aiohttp_swagger import *
from aiojobs.aiohttp import setup, spawn

from custom_engine import ENGINE_NAME
from log_configuratior import configure_logging

os.system('pip list')

server_status: str = 'ok'
notebooks_dir: str = '/home/jupyter-notebook/'
results_dir: str = '/home/jupyter-notebook/results/'
log_dir: str = '/home/jupyter-notebook/logs/'
tasks: dict = {}

configure_logging()
logger: logging.Logger = logging.getLogger('j-sp')


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
        result = json.load(file)
        notebooks_dir = result.get('notebooks', notebooks_dir)
        logger.info('notebooks_dir=%s', notebooks_dir)
        if notebooks_dir:
            create_dir(notebooks_dir)
        results_dir = result.get('results', results_dir)
        logger.info('results_dir=%s', results_dir)
        if results_dir:
            create_dir(results_dir)
        log_dir = result.get('logs', log_dir)
        logger.info('log_dir=%s', log_dir)
        if log_dir:
            create_dir(log_dir)
    except Exception as e:
        logger.error(f"Read '{path}' configuration failure", e)


async def req_status(req: Request):
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


def get_files(path, type):
    return [f.path for f in os.scandir(path) if f.is_file() and f.name.endswith(type) and f.name[0] != '.']


def replace_slashes(path: str):
    return path.replace('\\', '/')


def replace_local_to_server(path: str):
    if path.startswith(notebooks_dir):
        return replace_slashes(path).replace(notebooks_dir, './notebooks/', 1)
    elif path.startswith(results_dir):
        return replace_slashes(path).replace(results_dir, './results/', 1)
    else:
        return replace_slashes(path)


def replace_server_to_local(path: str):
    if path.startswith('./notebooks'):
        return replace_slashes(path).replace('./notebooks/', notebooks_dir, 1)
    elif path.startswith('./results'):
        return replace_slashes(path).replace('./results/', results_dir, 1)
    raise Exception("Path didn't start with notebooks or results folder")


async def req_notebooks(req: Request):
    """
    ---
    description: This end-point allows to get notebooks that could be requested. Query requires path to directory in which notebooks is searched.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return dictionary of available directories/files.
        "404":
            description: failed operation when queried directory doesn't exist or requested path didn't start with ./notebooks.
    """
    global logger
    path_arg = req.rel_url.query.get('path', '')
    logger.info('/files/notebooks?path={path}'.format(path=str(path_arg)))
    if path_arg == '':
        dirs = []
        if os.path.isdir(notebooks_dir):
            dirs = list(map(replace_local_to_server, get_dirs(notebooks_dir)))
        files = list(map(replace_local_to_server, get_files(notebooks_dir, '.ipynb')))

        dirs.sort()
        files.sort()

        return web.json_response({
            'directories': dirs,
            'files': files
        })

    try:
        path_converted = replace_server_to_local(path_arg)
    except:
        return web.HTTPNotFound(reason="Requested path didn't start with ./notebooks")

    if path_arg:
        if os.path.isdir(path_converted):
            dirs = list(map(replace_local_to_server, get_dirs(path_converted)))
            files = list(map(replace_local_to_server, get_files(path_converted, '.ipynb')))

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


async def req_jsons(req: Request):
    """
    ---
    description: This end-point allows to get jsonls that could be requested. Query requires path to directory in which jsonls is searched.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return dictionary of available directories/files.
        "404":
            description: failed operation when queried directory doesn't exist or requested path didn't start with ./results or ./notebooks.
    """
    global logger
    path_arg = req.rel_url.query.get('path', '')
    logger.info('/files/results?path={path}'.format(path=str(path_arg)))

    if path_arg == '':
        dirs_res = []
        dirs_note = []
        if os.path.isdir(results_dir):
            dirs_res = list(map(replace_local_to_server, get_dirs(results_dir)))

        if os.path.isdir(notebooks_dir):
            dirs_note = list(map(replace_local_to_server, get_dirs(notebooks_dir)))

        files_res = list(map(replace_local_to_server, get_files(results_dir, '.jsonl')))
        files_note = list(map(replace_local_to_server, get_files(notebooks_dir, '.jsonl')))

        dirs = list({*dirs_note, *dirs_res})
        files = list({*files_note, *files_res})

        dirs.sort()
        files.sort()

        return web.json_response({
            'directories': dirs,
            'files': files
        })

    try:
        path_converted = replace_server_to_local(path_arg)
    except:
        return web.HTTPNotFound(reason="Requested path didn't start with ./results or ./notebooks")
    if path_arg:
        if os.path.isdir(path_converted):
            dirs = list(map(replace_local_to_server, get_dirs(path_converted)))
            files = list(map(replace_local_to_server, get_files(path_converted, '.jsonl')))

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


async def req_files(req: Request):
    """
    ---
    description: This end-point allows to get files and directories. Query requires path to directory in which files and directories is searched.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return dictionary of available directories/files.
        "404":
            description: failed operation when queried directory doesn't exist or requested path didn't start with ./results or ./notebooks.
    """
    global logger
    path_arg = req.rel_url.query.get('path', '')
    logger.info('/files/all?path={path}'.format(path=str(path_arg)))

    if path_arg == '':
        dirs_res = []
        dirs_note = []
        if os.path.isdir(results_dir):
            dirs_res = list(map(replace_local_to_server, get_dirs(results_dir)))

        if os.path.isdir(notebooks_dir):
            dirs_note = list(map(replace_local_to_server, get_dirs(notebooks_dir)))

        files_res = list(map(replace_local_to_server, get_files(results_dir, '')))
        files_note = list(map(replace_local_to_server, get_files(notebooks_dir, '')))

        dirs = list({*dirs_note, *dirs_res})
        files = list({*files_note, *files_res})

        dirs.sort()
        files.sort()

        return web.json_response({
            'directories': dirs,
            'files': files
        })

    try:
        path_converted = replace_server_to_local(path_arg)
    except:
        return web.HTTPNotFound(reason="Requested path didn't start with ./results or ./notebooks")
    if path_arg:
        if os.path.isdir(path_converted):
            dirs = list(map(replace_local_to_server, get_dirs(path_converted)))
            files = list(map(replace_local_to_server, get_files(path_converted, '')))

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


async def req_parameters(req: Request):
    """
    ---
    description: This end-point allows to get parameters for notebook in requested path. Query requires path to notebook.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return json of file's parameters.
        "404":
            description: failed operation when queried file doesn't exist or requested path didn't start with ./notebooks.
    """
    global logger
    path = req.rel_url.query.get('path', '')
    logger.info('/files?path={path}'.format(path=str(path)))
    try:
        path_converted = replace_server_to_local(path)
    except:
        return web.HTTPNotFound(reason="Requested path didn't start with ./notebooks")
    if not path or not os.path.isfile(path_converted):
        return web.HTTPNotFound()
    params = pm.inspect_notebook(path_converted)
    return web.json_response(params)


async def launch_notebook(input_path, arguments, file_name, task_id):
    global tasks
    global logger
    logger.info(f'launching notebook {input_path} with {arguments}')
    start_execution = datetime.now()
    log_out: str = (log_dir + '/%s.log.ipynb' % file_name) if log_dir and file_name else None
    try:
        with pm.utils.chdir(input_path[:input_path.rfind('/')]):
            input_path = input_path[input_path.rfind('/') + 1:]
            pm.execute_notebook(
                input_path=input_path,
                output_path=log_out,
                parameters=arguments,
                engine_name=ENGINE_NAME,  # FIXME: use a separate engine for each UI user to avoid clash
            )
            logger.debug(f'successfully launched notebook {input_path}')
            if tasks.get(task_id):
                tasks[task_id] = {
                    'status': 'success',
                    'result': arguments.get('output_path')
                }
    except Exception as error:
        logger.error(f'failed to launch notebook {input_path}', error)
        if tasks.get(task_id):
            tasks[task_id] = {
                'status': 'failed',
                'result': error
            }
    finally:
        spent_time = (datetime.now() - start_execution).total_seconds()
        logger.info(f'ended launch notebook {input_path} with {arguments} spent_time {spent_time} sec')


def convert_parameter(parameter, notebook_path):
    parameter_type = parameter.get('type')
    parameter_value = parameter.get('value')
    if (parameter_type == 'file path'):
        try:
            parameter_path = replace_server_to_local(parameter_value)
        except:
            raise Exception(
                "Parameter {name} of type={type} with value={value} didn't start with ./notebooks or ./results"
                .format(name=parameter.get('name'), type=parameter_type, value=parameter_value)
            )

        return parameter_path
    else:
        return parameter_value


async def req_launch(req: Request):
    """
    ---
    description: This end-point allows to start notebook. Query requires path to notebook. Body requred to be dictionary of parameters.
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
    from uuid import uuid4
    global tasks
    global logger
    path_arg = req.rel_url.query.get('path', '')
    logger.info('/execute?path={path}'.format(path=str(path_arg)))
    if not req.can_read_body:
        return web.HTTPBadRequest(reason='Body with parameters not present')
    try:
        path_converted = replace_server_to_local(path_arg)
    except:
        return web.HTTPNotFound(reason="Requested path didn't start with ./notebooks")
    if not path_arg or not os.path.isfile(path_converted):
        return web.HTTPNotFound()
    if not os.path.exists(results_dir):
        return web.HTTPInternalServerError(reason='No output directory')
    notebook_name = path_converted.split('/')[-1].split('.')[0]
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
    file_name = notebook_name + '_' + timestamp
    output_path = results_dir + '/%s.jsonl' % str(file_name)
    req_json = await req.json()
    parameters = {}
    for key, parameter in req_json.items():
        try:
            parameters[key] = convert_parameter(parameter, path_converted)
        except Exception as error:
            return web.HTTPInternalServerError(reason=str(error))
    parameters['output_path'] = output_path
    task_id = str(uuid4())
    job = spawn(req, launch_notebook(path_converted, parameters, file_name, task_id))
    tasks[task_id] = {
        'status': 'in progress',
        'job': job
    }
    asyncio.shield(job)
    return web.json_response({'task_id': task_id})


async def req_file(req: Request):
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
            description: failed operation. requested file doesn't exist or requested path didn't start with ./results or ./notebooks.
    """
    global tasks
    global logger
    path = req.rel_url.query.get('path', '')
    logger.info('/file?path={path}'.format(path=str(path)))
    path_converted = replace_server_to_local(path)
    try:
        path_converted = replace_server_to_local(path)
    except:
        return web.HTTPNotFound(reason="Requested path didn't start with ./results or ./notebooks")
    if not path or not os.path.isfile(path_converted):
        return web.HTTPNotFound()
    file = open(path_converted, "r")
    content = file.read()
    file.close()
    return web.json_response({'result': content})


async def reqResult(req: Request):
    """
    ---
    description: This end-point allows to get result from requested task. Query requires task id from which result is required.
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
            description: failed operation. requested task doesn't exist or resulting file doesn't exist or status is unknown.
    """
    global tasks
    global logger
    task_id = req.rel_url.query.get('id')
    logger.info('/result?id={task_id}'.format(task_id=str(task_id)))
    task = tasks.get(task_id, None)
    if task is None:
        return web.HTTPNotFound(reason="Requested task doesn't exist")
    status = task.get('status', None)
    if status == 'in progress':
        return web.json_response({'status': status})
    elif status == 'success':
        path_param = task.get('result', '')
        if not path_param or not os.path.isfile(path_param):
            return web.HTTPNotFound(reason="Resulting file doesn't exist")
        file = open(path_param, "r")
        content = file.read()
        file.close()
        return web.json_response({'status': status, 'result': content, 'path': replace_local_to_server(path_param)})
    elif status == 'failed':
        error = task.get('result', Exception())
        return web.json_response({'status': status, 'result': str(error)})
    else:
        return web.HTTPNotFound()


async def req_stop(req: Request):
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
    task = tasks.pop(task_id, None)
    try:
        if task:
            await task.job.close()
    except:
        return web.HTTPInternalServerError(reason='failed to stop process')
    return web.HTTPOk()


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('config')
    cfg_path = vars(parser.parse_args()).get('config')
    if (cfg_path):
        read_config(cfg_path)

    app = web.Application()

    setup(app)
    app.router.add_route('GET', "/status", req_status)
    app.router.add_route('GET', "/files/notebooks", req_notebooks)
    app.router.add_route('GET', "/files/results", req_jsons)
    app.router.add_route('GET', "/files/all", req_files)
    app.router.add_route('GET', "/files", req_parameters)
    app.router.add_route('GET', "/file", req_file)
    app.router.add_route('POST', "/execute", req_launch)
    app.router.add_route('GET', "/result", reqResult)
    app.router.add_route('POST', "/stop", req_stop)
    setup_swagger(app)
    logger.info('starting server')
    web.run_app(app)

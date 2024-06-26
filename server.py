# Copyright 2024 Exactpro (Exactpro Systems Limited)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
os.system('pip list')

import subprocess
import sys
import papermill as pm
from aiohttp.web_request import Request
from aiohttp import web
from aiojobs.aiohttp import setup, spawn
from aiohttp_swagger import *
from glob import glob
import json
import datetime
import asyncio
from argparse import ArgumentParser
import logging

serverStatus: str = 'idle'
notebooksDir: str = '/home/jupyter-notebook/'
resultsDir: str = '/home/jupyter-notebook/results/'
logDir: str = '/home/jupyter-notebook/logs/'
tasks: dict = {}
logger: logging.Logger


def notebooksReg(path):
    return path + '/*.ipynb'


def resultsReg(path):
    return path + '/*.jsonl'


def resultsLog(path):
    return path + '/*.log.jsonl'


def createDir(path: str):
    if not os.path.exists(path):
        os.makedirs(path)


def readConf(path: str):
    global notebooksDir
    global resultsDir
    global logDir
    global logger
    try:
        file = open(path, "r")
        result = json.load(file)
        notebooksDir = result.get('notebooks', notebooksDir)
        logger.info('notebooksDir=%s', notebooksDir)
        if notebooksDir:
            createDir(notebooksDir)
        resultsDir = result.get('results', resultsDir)
        logger.info('resultsDir=%s',resultsDir)
        if resultsDir:
            createDir(resultsDir)
        logDir = result.get('logs', logDir)
        logger.info('logDir=%s', logDir)
        if logDir:
            createDir(logDir)
    except Exception as e:
        print(e)


async def reqStatus(req: Request):
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
    global serverStatus
    return web.json_response({'status': serverStatus})


def getDirs(path):
    return [f.path for f in os.scandir(path) if f.is_dir() and f.name[0] != '.']


def replaceSlashes(path: str):
    return path.replace('\\', '/')


async def reqFiles(req: Request):
    """
    ---
    description: This end-point allows to get files that could be requested.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return string array of available files.
    """
    path = path = req.rel_url.query.get('path')
    dirsNote = []
    dirsRes = []
    if path:
        if os.path.isdir(path):
            dirs = list(getDirs(path))
            files = glob(notebooksReg(path)) + glob(resultsReg(path))
            return web.json_response({
                'directories': dirs,
                'files': files
            })
        else:
            return web.HTTPNotFound()

    if os.path.isdir(notebooksDir):
        dirsNote = getDirs(notebooksDir)
    if os.path.isdir(resultsDir):
        dirsRes = getDirs(resultsDir)
    files = glob(notebooksReg(notebooksDir)) + glob(resultsReg(resultsDir))
    return web.json_response({
        'directories': list({*dirsNote, *dirsRes}),
        'files': files
    })


def replacePathLocalToServer(path: str):
    if path.startswith(notebooksDir):
        return replaceSlashes(path).replace(notebooksDir, './notebooks/', 1)
    elif path.startswith(resultsDir):
        return replaceSlashes(path).replace(resultsDir, './results/', 1)
    else:
        return replaceSlashes(path)


def replacePathServerToLocal(path: str):
    if path.startswith('./notebooks'):
        return replaceSlashes(path).replace('./notebooks/', notebooksDir, 1)
    elif path.startswith('./results'):
        return replaceSlashes(path).replace('./results/', resultsDir, 1)
    else:
        return replaceSlashes(path)


async def reqNotebooks(req: Request):
    """
    ---
    description: This end-point allows to get notebooks that could be requested.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return string array of available files.
    """
    global logger
    path = req.rel_url.query.get('path')
    logger.info('/files/notebooks?path={path}'.format(path=str(path)))
    pathConverted = path and replacePathServerToLocal(path)
    dirsNote = []
    if path:
        if os.path.isdir(pathConverted):
            dirs = list(map(replacePathLocalToServer, getDirs(pathConverted)))
            files = list(map(replacePathLocalToServer, glob(notebooksReg(pathConverted))))
            return web.json_response({
                'directories': dirs,
                'files': files
            })
        else:
            return web.HTTPNotFound()

    if os.path.isdir(notebooksDir):
        dirsNote = list(map(replacePathLocalToServer, getDirs(notebooksDir)))
    files = list(map(replacePathLocalToServer, glob(notebooksReg(notebooksDir))))
    return web.json_response({
        'directories': dirsNote,
        'files': files
    })


async def reqJsons(req: Request):
    """
    ---
    description: This end-point allows to get jsons that could be requested.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return string array of available files.
    """
    global logger
    path = req.rel_url.query.get('path')
    logger.info('/files/results?path={path}'.format(path=str(path)))
    pathConverted = path and replacePathServerToLocal(path)
    dirsNote = []
    dirsRes = []
    if path:
        if os.path.isdir(pathConverted):
            dirs = list(map(replacePathLocalToServer, getDirs(pathConverted)))
            files = list(map(replacePathLocalToServer, glob(resultsReg(pathConverted))))
            return web.json_response({
                'directories': dirs,
                'files': files
            })
        else:
            return web.HTTPNotFound()

    if os.path.isdir(resultsDir):
        dirsRes = list(map(replacePathLocalToServer, getDirs(resultsDir)))

    if os.path.isdir(notebooksDir):
        dirsNote = list(map(replacePathLocalToServer, getDirs(notebooksDir)))

    filesRes = list(map(replacePathLocalToServer, glob(resultsReg(resultsDir))))
    filesNote = list(map(replacePathLocalToServer, glob(resultsReg(notebooksDir))))

    return web.json_response({
        'directories': list({*dirsNote, *dirsRes}),
        'files': list({*filesNote, *filesRes})
    })


async def reqArguments(req: Request):
    """
    ---
    description: This end-point allows to get parameters for file in requested path.
    tags:
    - File operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return json of file's parameters.
        "404":
            description: requested file doesn't exist.
    """
    global logger
    path = req.rel_url.query['path']
    logger.info('/files?path={path}'.format(path=str(path)))
    pathConverted = path and replacePathServerToLocal(path)
    if not path or not os.path.isfile(pathConverted):
        return web.HTTPNotFound()
    params = pm.inspect_notebook(pathConverted)
    return web.json_response(params)


async def launchNotebook(input, arguments, file_name, task_id):
    global tasks
    global logger
    logger.info('launching notebook {input} with {arguments}'.format(input=input, arguments=arguments))
    logOut: str = (logDir + '/%s.log.ipynb' % file_name) if logDir and file_name else None
    try:
        with pm.utils.chdir(input[:input.rfind('/')]):
            input = input[input.rfind('/')+1:]
            pm.execute_notebook(input, logOut, arguments)
            logger.debug('successfully launched notebook {input}'.format(input=input))
            if tasks.get(task_id):
                tasks[task_id] = {
                    'status': 'success',
                    'result': arguments.get('output_path')
                }
    except Exception as error:
        logger.info('failed to launch notebook {input}'.format(input=input))
        logger.debug(error)
        if tasks.get(task_id):
            tasks[task_id] = {
                'status': 'failed',
                'result': error
            }
    finally:
        logger.info('ended launch notebook {input} with {arguments}'.format(input=input, arguments=arguments))


async def reqLaunch(req: Request):
    """
    ---
    description: This end-point allows to get file's parameters for requested path.
    tags:
    - Execution operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return json with path for resulting file.
        "400":
            description: body with parameters not present.
        "404":
            description: requested file doesn't exist.
        "503":
            description: server is currently busy.
    """
    from uuid import uuid4
    global tasks
    global logger
    path = req.rel_url.query.get('path')
    logger.info('/execute?path={path}'.format(path=str(path)))
    if not req.can_read_body:
        return web.HTTPBadRequest(reason='body with parameters not present')
    path = req.rel_url.query.get('path')
    pathConverted = path and replacePathServerToLocal(path)
    if not path or not os.path.isfile(pathConverted):
        return web.HTTPNotFound()
    if not os.path.exists(resultsDir):
        return web.HTTPInternalServerError(reason='no output directory')
    notebookName = pathConverted.split('/')[-1].split('.')[0];
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
    file_name = notebookName + '_' + timestamp
    output_path = resultsDir + '/%s.jsonl' % str(file_name)
    parameters = await req.json()
    parameters['output_path'] = output_path
    task_id = str(uuid4())
    job = spawn(req, launchNotebook(pathConverted, parameters, file_name, task_id))
    tasks[task_id] = {
        'status': 'in progress',
        'job': job
    }
    asyncio.shield(job)
    return web.json_response({'path': replacePathLocalToServer(output_path), 'task_id': task_id})


async def reqResult(req: Request):
    """
    ---
    description: This end-point allows to get result from requested path.
    tags:
    - Execution operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return resulting file's json.
        "400":
            description: body with parameters not present.
        "404":
            description: requested file doesn't exist.
        "503":
            description: server is currently busy.
    """
    global tasks
    global logger
    task_id = req.rel_url.query.get('id')
    logger.info('/result?id={task_id}'.format(task_id=str(task_id)))
    task = tasks.get(task_id, None)
    if not task:
        return web.HTTPNotFound()
    status = task.get('status', None)
    if status == 'in progress':
        return web.json_response({'status': status})
    elif status == 'success':
        path = task.get('result','')
        pathConverted = replacePathServerToLocal(path)
        if not path or not os.path.isfile(pathConverted):
            return web.HTTPNotFound()
        file = open(pathConverted, "r")
        content = file.read()
        file.close()
        return web.json_response({'status': status, 'result': content})
    elif status == 'failed':
        error = task.get('result', Exception())
        return web.json_response({'status': status, 'result': str(error)})
    else:
        return web.HTTPNotFound()

async def reqStop(req: Request):
    """
    ---
    description: This end-point allows to stop task by id.
    tags:
    - Execution operation
    produces:
    - application/json
    responses:
        "200":
            description: successful operation. Return resulting file's json.
        "400":
            description: body with parameters not present.
        "404":
            description: requested file doesn't exist.
        "503":
            description: server is currently busy.
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
    logging.basicConfig(filename='var/th2/config/log4py.conf', level=logging.DEBUG)
    logger=logging.getLogger('th2_common')
    parser = ArgumentParser()
    parser.add_argument('config')
    path = vars(parser.parse_args()).get('config')
    if (path):
        readConf(path)

    app = web.Application()

    setup(app)
    app.router.add_route('GET', "/status", reqStatus)
    app.router.add_route('GET', "/files/all", reqFiles)
    app.router.add_route('GET', "/files/notebooks", reqNotebooks)
    app.router.add_route('GET', "/files/results", reqJsons)
    app.router.add_route('GET', "/files", reqArguments)
    app.router.add_route('POST', "/execute", reqLaunch)
    app.router.add_route('GET', "/result", reqResult)
    app.router.add_route('POST', "/stop", reqStop)
    setup_swagger(app)
    logger.info('starting server')
    web.run_app(app)
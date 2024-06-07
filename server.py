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

import papermill as pm
from aiohttp.web_request import Request
from aiohttp import web
from aiojobs.aiohttp import setup, spawn
from aiohttp_swagger import *
from glob import glob
import json
import datetime
import os.path
import asyncio
from argparse import ArgumentParser

serverStatus: str = 'idle'
notebooksDir: str = '/home/jupyter-notebook/'
resultsDir: str = '/home/jupyter-notebook/results/'
logDir: str = '/home/jupyter-notebook/logs/'

def notebooksReg(path):
    return path + '/*.ipynb'

def resultsReg(path):
    return path + '/*.jsonl'

def resultsLog(path):
    return path + '/*.log.jsonl'

def createDir(path: str):
    try:
        if not os.path.exists(path):
            os.mkdir(path)
    except Exception as e:
        print(e)

import subprocess
import sys

def installRequirements(path):
    subprocess.check_call(" ".join([sys.executable, "-m pip install --no-cache-dir -r", path]))

def readConf(path: str):
    global notebooksDir
    global resultsDir
    global logDir
    try:
        file = open(path, "r")
        result = json.load(file)
        notebooksDir = result.get('notebooks', notebooksDir)
        if notebooksDir:
            createDir(notebooksDir)
        resultsDir = result.get('results', resultsDir)
        if resultsDir:
            createDir(resultsDir)
        logDir = result.get('logs', logDir)
        if logDir:
            createDir(logDir)
        #reqDir = result.get('requirements', None)
        #if reqDir:
        #    installRequirements(reqDir)
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
    return  [f.path for f in os.scandir(path) if f.is_dir() and f.name[0] != '.']

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
    path = req.rel_url.query.get('path')
    print('/files/notebooks?path={path}'.format(path = str(path)))
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
    path = req.rel_url.query.get('path')
    print('/files/results?path={path}'.format(path = str(path)))
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
    path = req.rel_url.query['path']
    print('/files?path={path}'.format(path = str(path)))
    pathConverted = path and replacePathServerToLocal(path)
    if not path or not os.path.isfile(pathConverted):
        return web.HTTPNotFound()
    params = pm.inspect_notebook(pathConverted)
    return web.json_response(params)



async def launchNotebook(input, arguments = None, file_name = None):
        global serverStatus
        print('launching notebook {input}'.format(input=input))
        serverStatus = 'busy'
        logOut: str = (logDir + '/%s.log.ipynb' % file_name) if logDir and file_name else None
        try:
            pm.execute_notebook(input, logOut, arguments)
            print('successfully launched notebook {input}'.format(input=input))
        except Exception as error:
            print('failed to launch notebook {input}'.format(input=input))
            print(error)
            return web.HTTPInternalServerError(reason=error)
        finally:
            serverStatus = 'idle'

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
    path = req.rel_url.query.get('path')
    print('/execute?path={path}'.format(path = str(path)))
    if serverStatus != 'idle':
        return web.HTTPServiceUnavailable(reason='server is currently busy')
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
    asyncio.shield(spawn(req, launchNotebook(pathConverted, parameters, file_name)))
    return web.json_response({'path': replacePathLocalToServer(output_path)})
        
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
    path = req.rel_url.query.get('path')
    print('/result?path={path}'.format(path=str(path)))
    if serverStatus != 'idle':
        return web.HTTPServiceUnavailable(reason='server is currently busy')
    pathConverted = path and replacePathServerToLocal(path)
    if not path or not os.path.isfile(pathConverted):
        return web.HTTPNotFound()
    file = open(pathConverted, "r")
    content = file.read()
    file.close()
    return web.json_response({'result' : content})

if __name__ == '__main__':
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
    setup_swagger(app)
    print('starting server')
    web.run_app(app)
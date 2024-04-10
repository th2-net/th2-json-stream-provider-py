import papermill as pm
from aiohttp.web_request import Request
from aiohttp import web
from aiojobs.aiohttp import setup, spawn
from aiohttp_swagger import *
from glob import glob
import json
import os.path
import asyncio
from argparse import ArgumentParser

serverStatus: str = 'idle'
notebooksDir: str = ''
resultsDir: str = ''

def notebooksReg():
    return notebooksDir + '/*.ipynb'

def resultsReg():
    return resultsDir + '/*.json'

def readConf(path: str):
    global notebooksDir
    global resultsDir
    file = open(path, "r")
    result = json.load(file)
    notebooksDir = result['notebooks'] or ''
    resultsDir = result['results'] or ''

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
    print(glob('notebooks' + '/*.ipynb'))
    print(notebooksDir)
    print(glob(notebooksReg()))
    files = glob(notebooksReg()) + glob(resultsReg())
    return web.json_response(files)

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
    files = glob(notebooksReg())
    return web.json_response(files)

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
    files = glob(resultsDir + resultsReg())
    return web.json_response(files)

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
    if not path or not os.path.isfile(path):
        return web.HTTPNotFound()
    params = pm.inspect_notebook(path)
    return web.json_response(params)

async def launchNotebook(input, arguments = None):
        global serverStatus
        serverStatus = 'busy'
        pm.execute_notebook(input, None, arguments)
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
    if serverStatus != 'idle':
        return web.HTTPServiceUnavailable(reason='server is currently busy')
    if not req.can_read_body:
        return web.HTTPBadRequest(reason='body with parameters not present')
    path = req.rel_url.query['path']
    if not path or not os.path.isfile(path):
        return web.HTTPNotFound()
    from uuid import uuid4
    output_path = resultsDir + '/%s.json' % str(uuid4())
    parameters = await req.json()
    parameters['output_path'] = output_path
    asyncio.shield(spawn(req, launchNotebook(path, parameters)))
    return web.json_response({'path': output_path})
        
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
    if serverStatus != 'idle':
        return web.HTTPServiceUnavailable(reason='server is currently busy')
    path = req.rel_url.query['path']
    if not path or not os.path.isfile(path):
        return web.HTTPNotFound()
    file = open(path, "r")
    result = json.load(file)
    return web.json_response(result)

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
    app.router.add_route('GET', "/files/jsons", reqJsons)
    app.router.add_route('GET', "/files", reqArguments)
    app.router.add_route('POST', "/execute", reqLaunch)
    app.router.add_route('GET', "/result", reqResult)
    setup_swagger(app)
    web.run_app(app)
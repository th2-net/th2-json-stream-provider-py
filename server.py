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
notebooksDir: str = ''
resultsDir: str = ''
logDir: str | None = None

def notebooksReg(path):
    return path + '/*.ipynb'

def resultsReg(path):
    return path + '/*.jsonl'

def resultsLog(path):
    return path + '/*.log.jsonl'

def readConf(path: str):
    global notebooksDir
    global resultsDir
    global logDir
    try:
        file = open(path, "r")
        result = json.load(file)
        notebooksDir = result['notebooks'] or ''
        resultsDir = result['results'] or ''
        logDir = result['logs'] or None
    except:
        print('there were error with reading conf file')

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

def replaceNotebooksPath(path: str):
    return replaceSlashes(path).replace(notebooksDir, '/notebooks')

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
    pathConverted = path and notebooksDir + path
    dirsNote = []
    if path:
        if os.path.isdir(pathConverted):
            dirs = list(map(replaceNotebooksPath, getDirs(pathConverted)))
            files = list(map(replaceNotebooksPath, glob(notebooksReg(pathConverted))))
            return web.json_response({
                'directories': dirs,
                'files': files
            })
        else:
            return web.HTTPNotFound()
        
    if os.path.isdir(notebooksDir):
        dirsNote = list(map(replaceNotebooksPath, getDirs(notebooksDir)))
    files = list(map(replaceNotebooksPath, glob(notebooksReg(notebooksDir))))
    return web.json_response({
        'directories': dirsNote,
        'files': files
    })

def replaceResultsPath(path: str):
    return replaceSlashes(path).replace(resultsDir, '/results')

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
    pathConverted = path and resultsDir + path
    dirsNote = []
    if path:
        if os.path.isdir(pathConverted):
            dirs = list(map(replaceResultsPath, getDirs(pathConverted)))
            files = list(map(replaceResultsPath, glob(resultsReg(pathConverted))))
            return web.json_response({
                'directories': dirs,
                'files': files
            })
        else:
            return web.HTTPNotFound()
        
    if os.path.isdir(resultsDir):
        dirsNote = list(map(replaceResultsPath, getDirs(resultsDir)))
    files = list(map(replaceResultsPath, glob(resultsReg(resultsDir))))
    return web.json_response({
        'directories': dirsNote,
        'files': files
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
    pathConverted = path and notebooksDir + path
    if not path or not os.path.isfile(pathConverted):
        return web.HTTPNotFound()
    params = pm.inspect_notebook(pathConverted)
    return web.json_response(params)



async def launchNotebook(input, arguments = None, file_name = None):
        global serverStatus
        serverStatus = 'busy'
        logOut: str = (logDir + '/%s.log.json' % file_name) if logDir and file_name else None
        try:
            pm.execute_notebook(input, logOut, arguments)
        except Exception as error:
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
    if serverStatus != 'idle':
        return web.HTTPServiceUnavailable(reason='server is currently busy')
    if not req.can_read_body:
        return web.HTTPBadRequest(reason='body with parameters not present')
    path = req.rel_url.query.get('path')
    pathConverted = path and notebooksDir + path
    if not path or not os.path.isfile(pathConverted):
        return web.HTTPNotFound()
    if not os.path.exists(resultsDir):
        return web.HTTPInternalServerError(reason='no output directory')
    notebookName = pathConverted.split('/')[-1].split('.')[0];
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    file_name = notebookName + '_' + timestamp
    output_path = resultsDir + '/%s.jsonl' % str(file_name)
    parameters = await req.json()
    parameters['output_path'] = output_path
    print(pathConverted)
    asyncio.shield(spawn(req, launchNotebook(pathConverted, parameters, file_name)))
    return web.json_response({'path': output_path.replace(resultsDir, '')})
        
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
    path = req.rel_url.query.get('path')
    pathConverted = path and resultsDir + path
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
    web.run_app(app)



import logging
from typing import Iterable
from fastapi import FastAPI
import pygit2
import uvicorn
from script_handler.handlers.schemas_handler import SchemasHandler
from script_handler.handlers.webhooks_handler import WebHooksHandlers
from script_handler.models.app_config import AppType

from script_handler.models.releases import Release

from .models.script import Script

from .handlers.gitlab_hook_handler import GitlabHookHandler
from .handlers.repository_handler import RepositoryHandler
from .handlers.script_handler import ScriptHandler
from .handlers.service_handler import ServiceHandler

from .handlers.user_handler import UserHandler
from .models.service import Service
from .runner.port_service import PortService
from .runner.runner_factory import VEnvRunnerFactory
from .git.git_repository import GitRepository,GitCallback
from .git.gitlab_service import GitlabService
from .handlers.auth_service import KeyCloakService
from .models.collections import RepositoryCollection, ObjCollection, UserCollection
from .models.repository import Repository
from starlette.middleware.authentication import AuthenticationMiddleware
from fastapi.middleware.cors import CORSMiddleware

from ._version import __version__

from loguru import logger
import sys

class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())



def setup_logging(log_level: str,json_logs: bool):
    # intercept everything at the root logger
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(log_level)

    # remove every other logger's handlers
    # and propagate to root logger
    for name in logging.root.manager.loggerDict.keys():
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    # configure loguru
    logger.configure(handlers=[{"sink": sys.stdout, "serialize": json_logs}])


class App:

    def __init__(
        self,
        git_service_url: str,
        git_service_token: str,
        git_hook_secret: str,
        auth_secret: str,
        audience: str,
        repos_root: str,
        venv_activator: str,
        run_dir: str,
        ports: Iterable[int],
        log_level: str,
        port: int,
        enable_lsp: bool,
        webhooks_secret: str
    ) -> None:
        self._git_service = GitlabService(git_service_url,git_service_token)
        self._auth_secret = auth_secret
        self._audience = audience
        self._git_hook_secret = git_hook_secret
        self._webhooks_secret = webhooks_secret

        GitRepository.set_git_credentials(
            GitCallback(credentials=pygit2.UserPass('oauth',git_service_token))
        )
        Repository.set_repos_root(repos_root)
        Release.set_root_path(run_dir)
        
        self._fast_api = FastAPI(
            openapi_url='/public/openapi.json',
            docs_url='/public/docs',
            redoc_url='/public/redoc',
            version=__version__

        )
        self._server = uvicorn.Server(
            uvicorn.Config(
                app=self._fast_api,
                log_level=logging.getLevelName(log_level),
                port=port,
                lifespan='off',
                host="0.0.0.0"
            )
        )
        self._server.force_exit = True # ignores waiting for background tasks on shutdown
        self._fast_api.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self._runner_factory = VEnvRunnerFactory(venv_activator,PortService(ports))
        self._venv_activator = venv_activator
        self._enable_lsp = enable_lsp
        setup_logging(logging.getLevelName(log_level),False)

    async def init(self):
        logging.info("Initializing application...")
        self._user_collection = UserCollection(
            (await self._git_service.get_all_users())
        )
        self._script_collection: ObjCollection[Script] = ObjCollection(AppType.STREAMLIT,AppType.PYTHON)
        self._service_collection: ObjCollection[Service] = ObjCollection(AppType.SERVICE)
        self._repo_collection = RepositoryCollection(
            (await self._git_service.get_all_repositories()),
            self._script_collection,
            self._service_collection,
            self._runner_factory
        )
        self._auth_service = KeyCloakService(self._auth_secret,self._audience,self._user_collection,self._git_service)
        self._fast_api.add_middleware(AuthenticationMiddleware,backend=self._auth_service,on_error=self._auth_service.default_on_error)
        user_handler = UserHandler(self._user_collection)
        gitlab_hook_handler = GitlabHookHandler(self._repo_collection,self._user_collection,self._git_service,self._git_hook_secret)
        self._fast_api.include_router(gitlab_hook_handler.router,prefix='/public')
        repo_handler = RepositoryHandler(self._repo_collection,self._user_collection,self._git_service,self._runner_factory,self._venv_activator,self._enable_lsp,gitlab_hook_handler)
        script_handler = ScriptHandler(self._script_collection)
        service_handler = ServiceHandler(self._service_collection)
        self._fast_api.include_router(user_handler.router)
        self._fast_api.include_router(repo_handler.router)
        self._fast_api.include_router(script_handler.router)
        self._fast_api.include_router(service_handler.router)



        webhooks_handler = WebHooksHandlers(
            self._webhooks_secret,
            self._script_collection,
            self._service_collection,
            self._user_collection
        )
        self._fast_api.include_router(webhooks_handler.router,prefix='/public')

        schemas_handler = SchemasHandler()
        self._fast_api.include_router(schemas_handler.router,prefix='/public')

    async def serve(self):
        await self._server.serve()

    async def cleanup(self):
        await self._git_service.close()
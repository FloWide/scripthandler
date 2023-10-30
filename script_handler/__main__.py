


import asyncio
from typing import Tuple
import pydantic_argparse 
from pydantic import BaseModel,Field

from .app import App
import os
import logging
from ._version import __version__

class Arguments(BaseModel):
    git_service_url: str = Field(description="Url to git service api")
    git_service_token: str = Field(description="Admin token for git service")
    git_hook_secret: str = Field(description="Secret for git service hooks")

    auth_secret: str = Field(description="Key used to verify auth token or file to the key")
    api_audience: str = Field(description="The api name in auth service",default='flowide-api')

    repos_root: str = Field(description="Directory where repositories will be cloned")
    venv_activator : str = Field(description="Path to virtual environment 'activate' executable")


    run_dir: str = Field(description="Directory where releases will be run from",default='/tmp')

    streamlit_ports: Tuple[int,int] = Field(default=(17001,17101),description="Port range to use for streamlit_applications")

    port: int = Field(default=11110,description="Port to run the server on")

    log_level: str = Field(default="DEBUG",description="Log level")

    enable_lsp: bool = Field(default=False,description="Enable python language server")

    webhooks_secret: str = Field(description="Secret that webhooks are checked against")



async def main():
    parser = pydantic_argparse.ArgumentParser(
        model=Arguments,
        version=__version__
    )
    args = parser.parse_typed_args()

    secret_key = ''
    if os.path.exists(args.auth_secret) and os.path.isfile(args.auth_secret):
        with open(args.auth_secret,'r') as f:
            secret_key = f.read()
    else:
        secret_key = args.auth_secret

    app = App(
        args.git_service_url,
        args.git_service_token,
        args.git_hook_secret,
        secret_key,
        args.api_audience,
        args.repos_root,
        args.venv_activator,
        args.run_dir,
        range(args.streamlit_ports[0],args.streamlit_ports[1]),
        args.log_level,
        args.port,
        args.enable_lsp,
        args.webhooks_secret
    )
    try:
        await app.init()
        await app.serve()
    except Exception as e:
        logging.error("Application crashed",exc_info=e)
    finally:
        await app.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
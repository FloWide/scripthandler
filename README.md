# StreamlitScriptHandler

This server creates a REST interface for streamlit script managing in a local directory.


## Command line args
```
usage: __main__.py [-h] --git-service-url GIT_SERVICE_URL --git-service-token GIT_SERVICE_TOKEN --git-hook-secret GIT_HOOK_SECRET --auth-secret AUTH_SECRET [--api-audience API_AUDIENCE] --repos-root REPOS_ROOT --venv-activator
                   VENV_ACTIVATOR --service-logs SERVICE_LOGS [--streamlit-ports STREAMLIT_PORTS [STREAMLIT_PORTS ...]] [--port PORT] [--log-level LOG_LEVEL]

required arguments:
  --git-service-url GIT_SERVICE_URL
                        Url to git service api
  --git-service-token GIT_SERVICE_TOKEN
                        Admin token for git service
  --git-hook-secret GIT_HOOK_SECRET
                        Secret for git service hooks
  --auth-secret AUTH_SECRET
                        Key used to verify auth token or file to the key
  --repos-root REPOS_ROOT
                        Directory where repositories will be cloned
  --venv-activator VENV_ACTIVATOR
                        Path to virtual environment 'activate' executable
  --service-logs SERVICE_LOGS
                        Directory where logs of services will be written

optional arguments:
  --api-audience API_AUDIENCE
                        The api name in auth service (default: flowide-api)
  --streamlit-ports STREAMLIT_PORTS [STREAMLIT_PORTS ...]
                        Port range to use for streamlit_applications (default: (17001, 17101))
  --port PORT           Port to run the server on (default: 11110)
  --log-level LOG_LEVEL
                        Log level (default: DEBUG)

help:
  -h, --help            show this help message and exit
```
### Example
```bash
python -m script_handler --git-service-url https://dev-gitlab.flowide.net \
                   --git-service-token token \
                   --git-hook-secret such_token_much_secret \
                   --auth-secret secret \
                   --repos-root /home/bgorzsony/repos \
                   --venv-activator /home/bgorzsony/.local/share/virtualenvs/streamlit_flowide-pfqCRh4Q/bin/activate \
                   --service-logs /home/bgorzsony/serivce-logs \
                   --streamlit-ports 17001 17100 \
                   --port 8000 \
                   --log-level DEBUG 
```

## Gitlab hooks

Gitlab should be set to send a System Hook with Repository update events to the `/public/gitlab/hook` path.


## Rest interface

Docs are under `/public/docs` or `/public/redoc`
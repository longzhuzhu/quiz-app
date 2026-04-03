import os
import sys

from dotenv import load_dotenv
from werkzeug.serving import run_simple


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, 'backend'))

load_dotenv(os.path.join(ROOT_DIR, '.env'))

from app import create_app


app = create_app()


if __name__ == '__main__':
    host = os.environ.get('APP_HOST', '0.0.0.0')
    port = int(os.environ.get('APP_PORT', '5003'))
    run_simple(host, port, app, use_debugger=False, use_reloader=False, threaded=True)

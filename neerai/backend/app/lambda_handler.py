"""AWS Lambda entrypoint (API Gateway HTTP API -> FastAPI via Mangum)."""
from mangum import Mangum

from .main import create_app

handler = Mangum(create_app(), lifespan="off")

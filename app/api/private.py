"""Private API responses must not cache PII or echo submitted credentials."""

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                response = await original(request)
            except RequestValidationError:
                # Even an unknown field name or a malformed JSON body may be a secret.
                response = JSONResponse({'detail': 'Invalid request fields or query parameters.'}, status_code=422)
            except HTTPException as exc:
                response = JSONResponse({'detail': exc.detail}, status_code=exc.status_code, headers=exc.headers)
            response.headers['Cache-Control'] = 'no-store'
            return response

        return handler

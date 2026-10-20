"""Verification capability tokens and uploaded documents never belong in access logs."""
import logging


class VerificationAccessFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn's access record arguments are client, method, path, HTTP version, status.
        # Omit this small public route family entirely rather than persisting its token.
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            return not args[2].startswith('/api/v1/verify/')
        return True


def install():
    logger = logging.getLogger('uvicorn.access')
    if not any(isinstance(f, VerificationAccessFilter) for f in logger.filters):
        logger.addFilter(VerificationAccessFilter())

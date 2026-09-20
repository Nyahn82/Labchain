"""Shared authentication cookies and same-origin checks for pre-session MFA."""
from fastapi import HTTPException
from app.config import settings


def same_origin(request):
    origin = request.headers.get('origin')
    if request.headers.get('sec-fetch-site') == 'cross-site' or (
            origin is not None and origin != f'{request.url.scheme}://{request.url.netloc}'):
        raise HTTPException(403, 'Cross-origin login is not allowed.')


def session_cookies(response, result):
    for name, token, httponly in ((settings.auth_session_cookie_name, result.session_token, True),
                                 (settings.auth_csrf_cookie_name, result.csrf_token, False)):
        response.set_cookie(name, token, max_age=settings.auth_session_ttl_minutes*60,
            httponly=httponly, secure=settings.auth_cookie_secure, samesite=settings.auth_cookie_samesite, path='/')


def clear_sessions(response):
    for name, httponly in ((settings.auth_session_cookie_name, True), (settings.auth_csrf_cookie_name, False)):
        response.delete_cookie(name, path='/', secure=settings.auth_cookie_secure,
            httponly=httponly, samesite=settings.auth_cookie_samesite)


def clear_challenge(response):
    response.delete_cookie(settings.mfa_challenge_cookie_name, path='/', secure=True, httponly=True, samesite='strict')

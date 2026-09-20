from fastapi import Request

from app.settings.service import SettingsService


def get_settings_service(request: Request) -> SettingsService:
    state = request.app.state
    return SettingsService(state.db, state.settings, state.secret_key)

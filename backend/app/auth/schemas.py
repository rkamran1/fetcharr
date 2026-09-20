from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
NewPassword = Annotated[str, Field(min_length=8)]


class AuthState(BaseModel):
    setup_required: bool


class NewAccount(BaseModel):
    username: Username
    password: NewPassword


class Credentials(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: NewPassword


class Me(BaseModel):
    username: str


class ApiKey(BaseModel):
    api_key: str

export type AuthState = { setup_required: boolean }
export type Me = { username: string }
export type Credentials = { username: string; password: string }
export type PasswordChange = { current_password: string; new_password: string }
export type ApiKey = { api_key: string }

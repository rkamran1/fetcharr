export const MIN_PASSWORD_LENGTH = 8

/** The reason a new password can't be used, or null. Mirrors the server's rule. */
export function passwordProblem(password: string, confirm: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH)
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`
  if (password !== confirm) return 'Passwords do not match.'
  return null
}

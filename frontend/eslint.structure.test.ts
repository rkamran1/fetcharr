// @vitest-environment node
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { ESLint } from 'eslint'
import { describe, expect, it } from 'vitest'

const ROOT = import.meta.dirname

async function lint(code: string): Promise<ESLint.LintResult> {
  const eslint = new ESLint({ cwd: ROOT })
  const [result] = await eslint.lintText(code, {
    filePath: path.join(ROOT, 'src/features/settings/pages/Probe.tsx'),
  })
  return result
}

describe('frontend structure (CLAUDE.md → Frontend structure)', () => {
  it('rejects a deep import into another feature', async () => {
    const result = await lint("import { listJobs } from '@/features/jobs/api'\nexport const x = listJobs\n")

    const restricted = result.messages.filter((m) => m.ruleId === 'no-restricted-imports')
    expect(restricted).toHaveLength(1)
    expect(restricted[0].message).toContain("Import a feature through its index")
  })

  it('allows importing a feature through its index', async () => {
    const result = await lint("import { listJobs } from '@/features/jobs'\nexport const x = listJobs\n")

    expect(result.messages.filter((m) => m.ruleId === 'no-restricted-imports')).toEqual([])
  })

  it('keeps src/api/client.ts down to request and ApiError', async () => {
    const source = await readFile(path.join(ROOT, 'src/api/client.ts'), 'utf8')

    const exported = [...source.matchAll(/^export (?:async function|function|class|const) (\w+)/gm)]
    expect(exported.map((match) => match[1]).sort()).toEqual(['ApiError', 'request'])
  })
})

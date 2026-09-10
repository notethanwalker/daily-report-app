# Manual Vercel Deployment Workaround

## Critical rule

**Do not re-enable Vercel Git auto-deploys.**

The repository intentionally keeps Git deployments disabled in `vercel.json`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "git": {
    "deploymentEnabled": false
  }
}
```

This is deliberate. Do not change that setting as a shortcut.

## Why this workaround exists

The Vercel connector/direct deployment action has been unreliable for this project. The proven workaround is to deploy a packaged copy of the exact validated `web/` source through a temporary helper branch, while leaving automatic Git deployment disabled.

The last confirmed successful production build used this pattern: Vercel downloaded `vercel-web-source.tgz` from a temporary GitHub release branch, unpacked it, then ran the normal Next.js build.

## Required deployment sequence

1. Finish development on a branch and validate it.
2. Merge only a validated commit into `main`.
3. Re-run CI/V4 validation on the exact merged `main` SHA.
4. Create a temporary helper branch from that exact `main` SHA, using a name such as:
   - `vercel-release-YYYYMMDD`
5. Add a one-time packaging workflow on the helper branch only. It should:
   - check out the helper branch,
   - run `tar -czf vercel-web-source.tgz web`,
   - commit the archive back to the same helper branch.
6. Confirm the archive exists and was generated from the exact validated `main` source.
7. Use the existing manual Vercel workaround/project configuration so Vercel's build downloads that helper-branch archive, unpacks it with `--strip-components=1`, and runs the normal Next.js build.
8. Confirm the deployment reaches `READY`.
9. Preserve the production alias:
   - `daily-report-app-pearl.vercel.app`
10. Smoke-test the production frontend and backend integration.
11. Remove temporary release artifacts/workflows after the deployment is confirmed.
12. Keep `git.deploymentEnabled=false` afterward.

## Known successful build command pattern

A prior successful production deployment used a `vercel-build` command equivalent to:

```sh
curl -L --fail https://raw.githubusercontent.com/notethanwalker/daily-report-app/<TEMP_RELEASE_BRANCH>/vercel-web-source.tgz -o /tmp/vercel-web-source.tgz \
  && tar -xzf /tmp/vercel-web-source.tgz --strip-components=1 \
  && next build
```

Use the current temporary release branch name in place of `<TEMP_RELEASE_BRANCH>`.

## Packaging workflow template

```yaml
name: Vercel Release Package Once
on:
  push:
    branches: [vercel-release-YYYYMMDD]
    paths: ['.github/workflows/vercel-release-package-once.yml']
permissions:
  contents: write
jobs:
  package:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - name: Package exact web source
        run: |
          set -euo pipefail
          tar -czf vercel-web-source.tgz web
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -f vercel-web-source.tgz
          git commit -m "Package web source for manual Vercel release"
          git push origin HEAD:vercel-release-YYYYMMDD
```

## Do not do these things

- Do **not** set `git.deploymentEnabled` to `true`.
- Do **not** rely on an ordinary push to `main` to deploy production.
- Do **not** assume `.deployment-trigger` causes a deployment while Git deploys are disabled.
- Do **not** deploy an unvalidated helper-branch commit that differs from the validated `main` source except for temporary release-packaging artifacts.
- Do **not** leave one-time write-enabled packaging workflows around after the release is complete.
- Do **not** burn Vercel deployment quota by repeatedly redeploying during debugging; batch changes and validate before deploying.

## Provenance check

Before declaring production current, verify all of the following:

- `main` SHA is known and validated.
- Render is running the matching backend SHA when backend code changed.
- the release archive was packaged from that exact validated source.
- the Vercel deployment is `READY`.
- `daily-report-app-pearl.vercel.app` points to the new deployment.
- production smoke checks pass.

If those cannot all be established, report deployment provenance as unresolved rather than assuming production matches `main`.

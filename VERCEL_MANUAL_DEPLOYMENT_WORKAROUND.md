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

The release archive must contain the exact validated `web/` tree. Vercel then downloads that archive, unpacks it into the build workspace, installs dependencies from the packaged app's own `package-lock.json`, and runs the normal Next.js build.

## Critical dependency-order correction

**Do not unpack the archive and immediately run `next build` using dependencies Vercel installed before the archive was extracted.**

A production audit on 2026-09-10 found that the older workaround did exactly that. Vercel's outer/bootstrap project installed Next.js 15.5.24 first, then `vercel-build` unpacked a repo tree whose `package.json` pins Next.js 16.3.4. The build therefore succeeded with the wrong framework dependency set.

After extracting the archive, always run `npm ci` before the build. This forces the build to use the packaged app's own lockfile and exact dependency versions.

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
7. Configure the manual Vercel build to:
   - download the current helper-branch archive,
   - unpack it with `--strip-components=1`,
   - run `npm ci` **after extraction**,
   - run `npm run build` (or `npx next build`) using those freshly installed locked dependencies.
8. Inspect the Vercel build log and verify the detected Next.js version matches `web/package.json` / `web/package-lock.json` before accepting the release.
9. Confirm the deployment reaches `READY`.
10. Preserve the production alias:
   - `daily-report-app-pearl.vercel.app`
11. Smoke-test the production frontend and backend integration.
12. Remove temporary release artifacts/workflows after the deployment is confirmed.
13. Keep `git.deploymentEnabled=false` afterward.

## Required build command pattern

Use a `vercel-build` command equivalent to:

```sh
curl -L --fail https://raw.githubusercontent.com/notethanwalker/daily-report-app/<TEMP_RELEASE_BRANCH>/vercel-web-source.tgz -o /tmp/vercel-web-source.tgz \
  && tar -xzf /tmp/vercel-web-source.tgz --strip-components=1 \
  && npm ci \
  && npm run build
```

Use the current temporary release branch name in place of `<TEMP_RELEASE_BRANCH>`.

After the build begins, confirm the build log's detected Next.js version matches the version pinned by the packaged app. A `READY` state alone is insufficient if the detected version is wrong.

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
- Do **not** build the extracted app with bootstrap dependencies installed before extraction.
- Do **not** accept a Vercel build without checking that its detected Next.js version matches the packaged lockfile.
- Do **not** deploy an unvalidated helper-branch commit that differs from the validated `main` source except for temporary release-packaging artifacts.
- Do **not** leave one-time write-enabled packaging workflows around after the release is complete.
- Do **not** burn Vercel deployment quota by repeatedly redeploying during debugging; batch changes and validate before deploying.

## Provenance check

Before declaring production current, verify all of the following:

- `main` SHA is known and validated.
- Render is running the latest expected **backend-changing** SHA when backend code changed.
- the release archive was packaged from the exact validated frontend source.
- the Vercel build downloaded the intended current helper branch, not an older release branch.
- the Vercel build detected the same Next.js version pinned in the packaged `web/package.json` / lockfile.
- the Vercel deployment is `READY`.
- `daily-report-app-pearl.vercel.app` points to the new deployment.
- production smoke checks pass.

If those cannot all be established, report deployment provenance as unresolved rather than assuming production matches `main`.

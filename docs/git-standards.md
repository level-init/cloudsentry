# Git Standards

CloudSentry uses GitHub (issues + pull requests). Workflow is issue-driven: create the issue first, then branch, then PR.

## Permanent Branches

- `main`: Production ready at all times. It should **always** work. No one pushes to `main` directly. Merges from `dev` to `main` happen when a slice on `dev` is verified and ready to ship.
- `dev`: Long-lived integration branch. All task branches are created from `dev` and merged back into `dev`. Integration checks happen here before merging into `main`.

Task branches are short-lived. Delete them after they merge into `dev`.

## Branch Naming

Every branch must link directly to a GitHub issue. Create the issue first; the issue number goes in the branch name.

### Branch Naming Format

```text
<issue_num>-<type>/<snake-case-title>
```

Where `<type>` matches your commit type (e.g., feat, fix, docs, refactor, task).

Examples:

```text
#12-task/add_idle_compute_detector
#13-fix/fix_savings_prediction_rounding
#14-refactor/extract_proposal_schema
#15-docs/add_coding_standards
```

**zsh note:** `#` starts a comment. Always quote branch names:

```bash
git checkout -b '#1-docs/scaffold_project_docs'
git push -u origin '#1-docs/scaffold_project_docs'
```

Multiple branches may reference the same issue if the issue is large. That is okay; the branch title must describe the specific change.

## Commit Standards

- Commit early and often; no multi-hundred-line commits when it can be avoided.
- All changes in a commit should serve a single purpose (do not mix refactor and docs in one commit).
- Commits should leave the project in a buildable state once application code exists (`api` and `web` build/test commands will be defined later).

### Commit Message Prefixes

All commits must start with one of:

| Prefix | Meaning |
| --- | --- |
| `task:` | A specific developer task or component implementation |
| `feat:` | Work toward a product feature |
| `fix:` | A bug fix |
| `refactor:` | Improvement without changing behavior |
| `docs:` | Documentation only |
| `test:` | Adding or updating tests |
| `wip:` | Work in progress; task not finished |

Keep the subject to one clear line.

Examples:

```text
docs: add product overview and git standards
feat: add idle compute detector for EC2-like resources
fix: correct monthly savings normalization window
wip: sketch proposal approval API routes
test: add verification baseline comparison cases
```

## Empty-Repo Bootstrap

`main` cannot exist as a real branch until there is a first commit. That first commit is the **only** time you commit on `main`. Keep it docs-only so `main` is never a broken app.

After that, every change goes:

```text
issue → task branch from dev → PR into dev → later PR dev into main
```

Bootstrap sequence:

1. Docs-only first commit on `main`
2. Create `dev` from that commit
3. Push `main` and `dev`
4. Protect `main` (no direct pushes) when the remote is configured

## Typical Developer Workflow

### 1. Claim your task

- Create or pick a GitHub issue
- Assign yourself
- Add an `In-progress` label if the board uses labels

### 2. Sync local `dev`

```bash
git checkout dev
git pull origin dev
```

### 3. Create your task branch

```bash
git checkout -b '#42-task/create_proposal_approval_api'
```

### 4. Code and commit

```bash
git add path/to/file
git commit -m "feat: add approval endpoint for optimization proposals"
```

Prefer staging specific files over `git add .` when unrelated local files exist.

### 5. Rebase onto latest `dev`

```bash
git checkout dev
git pull origin dev

git checkout '#42-task/create_proposal_approval_api'
git rebase dev
```

If there is a conflict: fix the files, `git add` them, then `git rebase --continue`.

### 6. Push to GitHub

```bash
git push -u origin '#42-task/create_proposal_approval_api'
```

If you already pushed and then rebased:

```bash
git push --force-with-lease origin '#42-task/create_proposal_approval_api'
```

### 7. Open a pull request

- Open a PR from **your task branch → `dev`** (not into `main`)
- Label the issue `In-Review`
- Describe what changed and why

### 8. Complete the pull request

- After review, merge into `dev`
- Delete the task branch
- Close the issue (or leave it open if more branches will follow)

### 9. Ship to production

When `dev` is verified (app builds, slice works):

- Open a PR from **`dev` → `main`**
- Merge that PR
- Never `git push origin main` with local commits that bypass review

## Collaboration Notes

CloudSentry may have more than one contributor. Keep PRs small and reviewable. Prefer merging into `dev` often so integration pain stays small. Do not treat `dev` as a personal sandbox; if work is unfinished, use `wip:` commits on a task branch, not long-lived divergence from `dev`.

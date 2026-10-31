# GitHub setup details (for the setup prompt)

Replace `OWNER` with Adhi's GitHub username.

## Ruleset: lock `main`

```bash
gh api -X POST repos/OWNER/kiln/rulesets --input - << 'JSON'
{
  "name": "lock-main",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/heads/main"], "exclude": [] } },
  "bypass_actors": [
    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request" }
  ],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "update" },
    { "type": "pull_request", "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false } },
    { "type": "required_status_checks", "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [ { "context": "source-is-dev" } ] } }
  ]
}
JSON
```

- `update` blocks everyone from changing `main`; the bypass lets the **repository admin** (role id 5) through, and `bypass_mode: pull_request` means even the admin only gets through via a pull request.
- After creating it, open **Settings → Rules → Rulesets → lock-main** and confirm the bypass list shows **Repository admin**. If it shows a different role, fix it there.

## Ruleset: protect `dev`

```bash
gh api -X POST repos/OWNER/kiln/rulesets --input - << 'JSON'
{
  "name": "protect-dev",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/heads/dev"], "exclude": [] } },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "pull_request", "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false } }
  ]
}
JSON
```

## Discord alerts for pushes and pull requests

Discord accepts GitHub's webhook format when `/github` is added to the end of a Discord webhook URL.

```bash
gh api -X POST repos/OWNER/kiln/hooks \
  -f name=web -F active=true \
  -f 'events[]=push' -f 'events[]=pull_request' -f 'events[]=pull_request_review' \
  -f "config[url]=${DISCORD_WEBHOOK_URL}/github" \
  -f 'config[content_type]=json'
```

Use a **different** Discord webhook from the night runner's, in a channel where Adhi gets pinged.

## Team workflow
1. Everyone works on a feature branch named after themselves and the task, e.g. `cj/thermo-agent`.
2. Open a PR into `dev`. Any teammate may merge it once it runs.
3. Only Adhi opens and merges PRs from `dev` into `main`, at each gate (Gate 0, Gate 1, code freeze, Sunday release).

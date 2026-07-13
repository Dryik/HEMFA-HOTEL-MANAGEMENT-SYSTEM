# Release and Odoo.sh Workflow

## Branches

- `dev`: integration branch; Odoo.sh development build installs/updates all hotel addons and runs tagged tests.
- `staging`: release candidate; Odoo.sh staging build upgrades a production clone and runs migration/UAT checks.
- `main`: production; accepts only a reviewed, signed-off staging release.

GitHub branch protection must require pull requests, the `Static validation` check, and at least one reviewer. Odoo.sh branch types and production promotion are configured in the Odoo.sh project UI.

## Promotion

1. Merge reviewed work into `dev` and verify the Odoo.sh development build.
2. Promote the exact commit to `staging`; restore a recent production clone and execute upgrade, migration, security, financial, and browser smoke tests.
3. Record departmental acceptance and reconciliation evidence.
4. Merge the exact staging commit into `main`, tag it, and deploy from Odoo.sh.

Rollback is database restore plus the previously tagged code release. Upgrade scripts must therefore be non-destructive and idempotent; in-place schema downgrades are not supported.

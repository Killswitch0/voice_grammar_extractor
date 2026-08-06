# Backing up `analysis/` to your own private repo

`analysis/` holds your accumulated learning data — mistake patterns, scores,
session history. The root `.gitignore` deliberately excludes it from this
project's own repo (which may be public), so **it is not backed up
anywhere by default.** If you lose the folder, you lose the history.

This is a one-time, ~10 minute setup for a private off-site backup that's
entirely separate from this project's repo.

## 1. Create a private repo

On GitHub (or any git host), create a new **empty, private** repository —
e.g. `<your-project>-analysis`. Don't add a README/license/gitignore, leave
it fully empty.

## 2. (Recommended) Use a dedicated SSH identity

If your machine's default git identity is a work account, pushing personal
speech data under it is easy to do by accident. A separate SSH host alias
makes the identity explicit and prevents that. Add to `~/.ssh/config`:

```
Host <alias>              # e.g. github-personal
    HostName github.com
    User git
    IdentityFile ~/.ssh/<your_personal_key>
    IdentitiesOnly yes
```

Test it: `ssh -T git@<alias>` should greet you with your GitHub username.

## 3. Turn `analysis/` into its own git repo

This nests a second, independent git repo inside `analysis/` — safe to do,
since the outer repo's `.gitignore` already excludes everything in here
except this file and `sessions/README.txt`.

```bash
cd analysis
git init
git branch -M main
git remote add origin git@<alias>:<you>/<your-analysis-repo>.git

# Local identity for THIS repo only — overrides your global git config,
# so commits here never carry a work email even if your global config does.
git config user.name "<your-name-or-handle>"
git config user.email "<your-personal-email>"
```

## 4. Decide what to actually back up

Recommended: back up the **derived analysis**, not the **raw dialogue**.
`memory.md`, `scores_history.csv`, `conversation_focus_log.md`, and the
session reports (`sessions/*.md`) are the valuable long-term signal. The raw
transcripts (`sessions/*.txt`, `sessions/*.annotated.txt`) are the actual
words you said — most people are more comfortable keeping those local-only,
even in a private repo. Add to `analysis/.gitignore`:

```
sessions/*.txt
!sessions/README.txt
```

## 5. First commit and push

```bash
git add -A
git commit -m "Initial backup"
git push -u origin main
```

## 6. Everyday use: a one-command backup

Add this function to your shell profile (`~/.zshrc` / `~/.bashrc`), with
the placeholders filled in. It refuses to push if the remote doesn't match
what you expect, or if the SSH identity it authenticates as isn't your
account — so a misconfigured alias or an accidental remote change fails
loudly instead of silently pushing personal data under the wrong identity.

```zsh
backup-analysis() {
  local dir=<absolute-path-to-this-project>/analysis
  local expected_remote="git@<alias>:<you>/<your-analysis-repo>.git"
  local expected_user="<your-github-username>"
  local identity_file=~/.ssh/<your_personal_key>
  local ssh_cmd="ssh -i $identity_file -o IdentitiesOnly=yes -o BatchMode=yes"

  cd "$dir" || return 1

  local actual_remote
  actual_remote=$(git remote get-url origin 2>/dev/null)
  if [[ "$actual_remote" != "$expected_remote" ]]; then
    echo "Aborting: remote is '$actual_remote', expected the personal backup repo."
    cd - > /dev/null; return 1
  fi

  if [[ ! -f "$identity_file" ]]; then
    echo "Aborting: personal SSH key not found at $identity_file."
    cd - > /dev/null; return 1
  fi

  local whoami_output
  whoami_output=$(${=ssh_cmd} -T git@<alias> 2>&1)
  if [[ "$whoami_output" != *"Hi $expected_user!"* ]]; then
    echo "Aborting: SSH identity check failed. Got: $whoami_output"
    cd - > /dev/null; return 1
  fi

  git add -A
  if git diff --cached --quiet; then
    echo "Nothing new to back up."
  else
    git commit -m "session $(date +%F)"
    GIT_SSH_COMMAND="$ssh_cmd" git push origin main
  fi
  cd - > /dev/null
}
```

`${=ssh_cmd}` is zsh syntax for splitting the string into words (zsh doesn't
word-split unquoted variables by default, unlike bash). If you're on bash,
drop the `=` — plain `$ssh_cmd` word-splits there already.

After that, running `backup-analysis` from anywhere backs up your latest
session in one command.
